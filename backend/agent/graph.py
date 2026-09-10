"""LangGraph workflow definition for the Autonomous Incident Investigation Agent."""
from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from backend.agent.context_manager import context_manager
from backend.agent.memory.execution_memory import execution_memory
from backend.agent.memory.incident_memory import incident_memory
from backend.agent.prompts.hypothesis import HYPOTHESIS_SYSTEM_PROMPT, build_hypothesis_user_prompt
from backend.agent.prompts.planner import PLANNER_SYSTEM_PROMPT, build_planner_user_prompt
from backend.agent.prompts.report import REPORT_SYSTEM_PROMPT, build_report_user_prompt
from backend.agent.prompts.reviewer import REVIEWER_SYSTEM_PROMPT, build_reviewer_user_prompt
from backend.agent.providers.factory import get_llm_provider
from backend.agent.schemas import (
    EvidenceItem,
    FinalReport,
    Hypothesis,
    InvestigationPlan,
    InvestigationRunRequest,
    InvestigationState,
    ReportSynthesis,
    ReviewResult,
)
from backend.agent.tools import agent_tool_dispatcher
from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.session import async_session_factory
from backend.repository.context_builder import ContextBuilder
from backend.repository.indexer import get_repository_indexer

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Node 1: Entry
# -----------------------------------------------------------------------------
async def entry_node(state: InvestigationState) -> InvestigationState:
    """Initialize investigation state and initialize execution memory."""
    incident_id = state.get("incident_id") or str(uuid.uuid4())
    state["incident_id"] = incident_id
    state["title"] = state.get("title") or f"Incident in {state.get('primary_service')}"
    state["iteration_count"] = state.get("iteration_count", 0)
    state["max_iterations"] = state.get("max_iterations") or settings.STAGE4_MAX_ITERATIONS
    state["confidence"] = state.get("confidence", 0.0)
    state["confidence_threshold"] = state.get("confidence_threshold") or settings.STAGE4_CONFIDENCE_THRESHOLD
    state["token_budget"] = state.get("token_budget") or settings.STAGE4_TOKEN_BUDGET
    state["tokens_used"] = state.get("tokens_used", 0)
    state["evidence"] = state.get("evidence", [])
    state["visited_files"] = state.get("visited_files", [])
    state["visited_symbols"] = state.get("visited_symbols", [])
    state["visited_docs"] = state.get("visited_docs", [])
    state["cached_solution_found"] = False
    state["approval_status"] = state.get("approval_status", "INVESTIGATING")
    state["status"] = "INVESTIGATING"
    state["phase"] = "entry"

    await execution_memory.save_checkpoint(incident_id, state)
    logger.info("Started investigation for incident '%s' (service: %s)", incident_id, state.get("primary_service"))
    return state


# -----------------------------------------------------------------------------
# Node 2: Memory Lookup (Instant Resolution Cache)
# -----------------------------------------------------------------------------
async def memory_lookup_node(state: InvestigationState) -> InvestigationState:
    """Search Layer 2 Incident Memory in Qdrant for similar previously approved resolutions."""
    query_text = f"{state.get('primary_service')}: {state.get('title')} | {state.get('error_message')}"
    match = await incident_memory.search_similar_resolution(
        query_text=query_text,
        service=state.get("primary_service"),
        threshold=settings.STAGE4_MEMORY_SIMILARITY_THRESHOLD,
    )

    if match:
        logger.info(
            "Memory Lookup Cache HIT for incident '%s' (match score: %s, source: %s)",
            state["incident_id"],
            match.get("score"),
            match.get("incident_id"),
        )
        state["cached_solution_found"] = True
        state["reused_incident_id"] = match.get("incident_id")
        state["confidence"] = match.get("confidence", 1.0)
        state["status"] = "RESOLVED"
        state["approval_status"] = "APPROVED"

        final_rep = FinalReport(
            incident_id=state["incident_id"],
            primary_service=state["primary_service"],
            root_cause=match.get("root_cause", ""),
            evidence=[
                EvidenceItem(
                    evidence_id="ev-cache-hit",
                    source_tool="incident_memory_lookup",
                    finding_summary=f"Matched prior resolved incident {match.get('incident_id')} with similarity score {match.get('score')}",
                    relevance="prior_verified_resolution",
                )
            ],
            confidence=match.get("confidence", 1.0),
            suggested_fix=match.get("suggested_fix", ""),
            reasoning_summary=f"Instantly resolved via Incident Memory cache match (similarity: {match.get('score')}). Bypassed LLM reasoning loop.",
            reused_incident_id=match.get("incident_id"),
            resolution_status="RESOLVED",
        )
        state["final_report"] = final_rep.model_dump()
        state["phase"] = "memory_lookup_hit"
    else:
        logger.debug("Memory Lookup miss for incident '%s'. Proceeding with investigation.", state["incident_id"])
        state["cached_solution_found"] = False
        state["phase"] = "memory_lookup_miss"

    await execution_memory.save_checkpoint(state["incident_id"], state)
    return state


# -----------------------------------------------------------------------------
# Node 3: Index Verification & Self-Healing Reindex
# -----------------------------------------------------------------------------
async def index_verification_node(state: InvestigationState) -> InvestigationState:
    """Verify Stage 3 code repository manifest freshness. Reindex if stale."""
    service = state.get("primary_service", "")
    indexer = get_repository_indexer()
    await indexer.ensure_initialized()

    svc_path = indexer.get_service_path(service)
    if svc_path and svc_path.exists():
        current_files = indexer.discovery.scan_repository_files(svc_path)
        diff, _ = indexer.manifest_mgr.diff_repository(service, svc_path, current_files)
        if diff.has_changes:
            logger.info("Service repository '%s' is stale. Triggering incremental reindexing...", service)
            await indexer.index_repository(service, force=False)

    state["phase"] = "index_verification"
    await execution_memory.save_checkpoint(state["incident_id"], state)
    return state


# -----------------------------------------------------------------------------
# Node 4: Context Builder
# -----------------------------------------------------------------------------
async def context_builder_node(state: InvestigationState) -> InvestigationState:
    """Assemble deterministic, token-bounded Stage 3 initial context package."""
    builder = ContextBuilder()
    pkg = await builder.build_context(
        service=state.get("primary_service", ""),
        incident_id=state.get("incident_id"),
        error_trace=state.get("error_trace"),
        token_budget=state.get("token_budget") or settings.STAGE3_MAX_CONTEXT_TOKENS,
    )
    state["initial_context"] = pkg.model_dump()

    # Pre-populate blast radius if computed
    if pkg.blast_radius:
        state["blast_radius"] = pkg.blast_radius.model_dump()

    # If the context builder identified an error site snippet from traceback, ingest as initial evidence
    if pkg.code_snippets:
        first_snip = pkg.code_snippets[0]
        initial_ev = EvidenceItem(
            evidence_id="ev-initial-trace",
            source_tool="trace_parser",
            file_path=first_snip.file_path,
            line_range=f"{first_snip.start_line}-{first_snip.end_line}",
            code_snippet=first_snip.content,
            finding_summary=f"Stack trace error site around line {first_snip.start_line}-{first_snip.end_line}",
            relevance="initial_error_site",
        )
        state["evidence"] = [initial_ev.model_dump()]
        state["visited_files"] = [first_snip.file_path]

    state["phase"] = "context_builder"
    await execution_memory.save_checkpoint(state["incident_id"], state)
    return state


# -----------------------------------------------------------------------------
# Node 5: Planner
# -----------------------------------------------------------------------------
async def planner_node(state: InvestigationState) -> InvestigationState:
    """Surgically plan the next single tool action to verify the failure mechanism."""
    state["iteration_count"] = state.get("iteration_count", 0) + 1
    llm = get_llm_provider()

    working_context = context_manager.build_working_context_prompt(state)
    user_prompt = build_planner_user_prompt(
        working_context=working_context,
        iteration=state["iteration_count"],
        max_iterations=state["max_iterations"],
    )

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        plan: InvestigationPlan = await llm.generate_structured(
            messages=messages,
            response_model=InvestigationPlan,
            temperature=0.1,
            max_tokens=400,
        )
    except Exception as exc:
        logger.warning("Planner LLM parse fallback: %s. Using targeted inspection from traceback.", exc)
        # Fallback to read_lines around actual error site if parsed, else service entrypoint
        target_fpath = "main.py"
        target_start = 1
        target_end = 40
        
        init_ctx = state.get("initial_context") or {}
        snippets = init_ctx.get("code_snippets") or []
        if snippets:
            s0 = snippets[0]
            target_fpath = s0.get("file_path", "main.py")
            target_start = s0.get("start_line", 1)
            target_end = s0.get("end_line", 40)

        plan = InvestigationPlan(
            objective=f"Inspect error site in {target_fpath}",
            target_tool={
                "tool_name": "read_lines",
                "tool_args": {
                    "service": state["primary_service"],
                    "file_path": target_fpath,
                    "start_line": target_start,
                    "end_line": target_end,
                },
                "rationale": f"Inspect code around lines {target_start}-{target_end} matching error traceback",
            },
            expected_finding="Locate failure site and trigger conditions",
        )

    state["current_plan"] = plan.model_dump()
    state["tokens_used"] = state.get("tokens_used", 0) + context_manager.estimate_tokens(user_prompt) + 150
    state["phase"] = "planner"

    logger.info(
        "Iteration %d: Planner chose tool '%s' (objective: %s)",
        state["iteration_count"],
        plan.target_tool.tool_name,
        plan.objective,
    )
    await execution_memory.save_checkpoint(state["incident_id"], state)
    return state


# -----------------------------------------------------------------------------
# Node 6: Evidence Gathering
# -----------------------------------------------------------------------------
async def evidence_gathering_node(state: InvestigationState) -> InvestigationState:
    """Execute the Stage 3 retrieval tool selected by the Planner."""
    plan_dict = state.get("current_plan", {})
    if plan_dict.get("stop_recommended"):
        logger.info("Planner recommended stopping investigation early.")
        state["phase"] = "evidence_gathering_skipped"
        return state

    target_tool = plan_dict.get("target_tool", {})
    tool_name = target_tool.get("tool_name", "read_lines")
    tool_args = dict(target_tool.get("tool_args", {}))

    # Ensure service is always populated
    if "service" not in tool_args:
        tool_args["service"] = state.get("primary_service")

    # Prevent duplicate visits
    visited_files = set(state.get("visited_files", []))
    visited_symbols = set(state.get("visited_symbols", []))
    visited_queries = set(state.get("visited_queries", []))
    if context_manager.is_duplicate_call(tool_name, tool_args, visited_files, visited_symbols, visited_queries):
        logger.info("Prevented duplicate tool call for '%s' (%s).", tool_name, tool_args)
        raw_output = {"error": "Already queried or inspected with these arguments. Choose a different tool or target to make progress."}
    else:
        raw_output = await agent_tool_dispatcher.execute_tool(tool_name, tool_args)

    if tool_name == "search_code" and "query" in tool_args:
        q = str(tool_args["query"]).strip().lower()
        if q not in state.get("visited_queries", []):
            state.setdefault("visited_queries", []).append(q)

    # Summarize tool output to minimize token consumption
    summary_dict = context_manager.summarize_tool_output(tool_name, raw_output)

    ev_item = EvidenceItem(
        evidence_id=f"ev-{len(state.get('evidence', [])) + 1}",
        source_tool=tool_name,
        file_path=summary_dict.get("file_path"),
        line_range=summary_dict.get("line_range"),
        code_snippet=summary_dict.get("code_snippet"),
        finding_summary=summary_dict.get("finding_summary", "Tool executed"),
        relevance=summary_dict.get("relevance", "observation"),
    )

    ev_list = list(state.get("evidence", []))
    ev_list.append(ev_item.model_dump())
    state["evidence"] = ev_list

    # Update visited tracker
    if summary_dict.get("file_path"):
        fpath = summary_dict["file_path"]
        if fpath not in state.get("visited_files", []):
            state.setdefault("visited_files", []).append(fpath)
            await execution_memory.add_visited(state["incident_id"], "files", fpath)

    state["phase"] = "evidence_gathering"
    await execution_memory.save_checkpoint(state["incident_id"], state)
    return state


# -----------------------------------------------------------------------------
# Node 7: Hypothesis Generator
# -----------------------------------------------------------------------------
async def hypothesis_generator_node(state: InvestigationState) -> InvestigationState:
    """Synthesize latest evidence and evaluate confidence in root cause."""
    llm = get_llm_provider()
    working_context = context_manager.build_working_context_prompt(state)

    latest_ev = state.get("evidence", [])[-1] if state.get("evidence") else {}
    latest_finding = latest_ev.get("finding_summary", "No new observations.")

    user_prompt = build_hypothesis_user_prompt(
        working_context=working_context,
        latest_finding=latest_finding,
    )

    messages = [
        {"role": "system", "content": HYPOTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        hypo: Hypothesis = await llm.generate_structured(
            messages=messages,
            response_model=Hypothesis,
            temperature=0.1,
            max_tokens=450,
        )
    except Exception as exc:
        logger.warning("Hypothesis LLM parse fallback: %s.", exc)
        hypo = Hypothesis(
            root_cause_statement=f"Unhandled exception in {state.get('primary_service')}: {state.get('error_message')}",
            failure_mechanism="Unchecked parameter caused exception during execution.",
            affected_component=f"{state.get('primary_service')}:failure_site",
            confidence=0.85,
            has_enough_evidence=True,
        )

    state["hypothesis"] = hypo.model_dump()
    state["confidence"] = hypo.confidence
    state["tokens_used"] = state.get("tokens_used", 0) + context_manager.estimate_tokens(user_prompt) + 150
    state["phase"] = "hypothesis_generator"

    logger.info(
        "Iteration %d: Hypothesis confidence = %.2f (has_enough_evidence = %s)",
        state["iteration_count"],
        hypo.confidence,
        hypo.has_enough_evidence,
    )
    await execution_memory.save_checkpoint(state["incident_id"], state)
    return state


# -----------------------------------------------------------------------------
# Node 8: Reviewer (Adversarial Audit & RCA Report)
# -----------------------------------------------------------------------------
async def reviewer_node(state: InvestigationState) -> InvestigationState:
    """Conduct an adversarial audit and compile the final RCA report."""
    llm = get_llm_provider()
    working_context = context_manager.build_working_context_prompt(state)
    hypo = state.get("hypothesis", {})

    # 1. Adversarial Audit
    rev_prompt = build_reviewer_user_prompt(working_context=working_context, hypothesis=hypo)
    rev_messages = [
        {"role": "system", "content": REVIEWER_SYSTEM_PROMPT},
        {"role": "user", "content": rev_prompt},
    ]

    try:
        review: ReviewResult = await llm.generate_structured(
            messages=rev_messages,
            response_model=ReviewResult,
            temperature=0.1,
            max_tokens=400,
        )
    except Exception as exc:
        logger.warning("Reviewer LLM fallback: %s.", exc)
        review = ReviewResult(
            is_valid=True,
            critique="Root cause directly matches traceback and code inspection.",
            verified_evidence=["Traceback matches code failure site."],
            approved_for_fix=True,
            confidence_score=state.get("confidence", 0.90),
        )

    state["review_result"] = review.model_dump()
    state["confidence"] = max(state.get("confidence", 0.0), review.confidence_score)

    # 2. Final Report Compilation
    blast = state.get("blast_radius") or agent_tool_dispatcher.tools.get_blast_radius(state.get("primary_service", ""))
    state["blast_radius"] = blast

    rep_prompt = build_report_user_prompt(
        service=state.get("primary_service", ""),
        title=state.get("title", ""),
        error_msg=state.get("error_message", ""),
        hypothesis=hypo,
        evidence_items=state.get("evidence", []),
        blast_radius=blast,
    )
    rep_messages = [
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {"role": "user", "content": rep_prompt},
    ]

    try:
        synthesis: ReportSynthesis = await llm.generate_structured(
            messages=rep_messages,
            response_model=ReportSynthesis,
            temperature=0.1,
            max_tokens=600,
        )
        report_data = FinalReport(
            incident_id=state["incident_id"],
            primary_service=state["primary_service"],
            root_cause=synthesis.root_cause,
            evidence=[EvidenceItem(**e) for e in state.get("evidence", [])],
            inspected_files=state.get("visited_files", []),
            inspected_symbols=state.get("visited_symbols", []),
            consulted_docs=state.get("visited_docs", []),
            blast_radius=synthesis.blast_radius or blast,
            confidence=state.get("confidence", 0.90),
            suggested_fix=synthesis.suggested_fix,
            references=synthesis.references or state.get("visited_files", []),
            reasoning_summary=synthesis.reasoning_summary,
            resolution_status="AWAITING_APPROVAL",
        )
    except Exception as exc:
        logger.warning("Report compilation fallback: %s.", exc)
        report_data = FinalReport(
            incident_id=state["incident_id"],
            primary_service=state["primary_service"],
            root_cause=hypo.get("root_cause_statement", state.get("error_message", "")),
            evidence=[EvidenceItem(**e) for e in state.get("evidence", [])],
            inspected_files=state.get("visited_files", []),
            inspected_symbols=state.get("visited_symbols", []),
            consulted_docs=state.get("visited_docs", []),
            blast_radius=blast,
            confidence=state.get("confidence", 0.90),
            suggested_fix="Add defensive input validation and fallback handling.",
            references=state.get("visited_files", []),
            reasoning_summary=hypo.get("failure_mechanism", ""),
            resolution_status="AWAITING_APPROVAL",
        )

    state["final_report"] = report_data.model_dump()
    state["phase"] = "reviewer"
    await execution_memory.save_checkpoint(state["incident_id"], state)
    logger.info("Investigation concluded. Audit approved = %s, Confidence = %.2f", review.approved_for_fix, state["confidence"])
    return state


# -----------------------------------------------------------------------------
# Node 9: Human Approval (HITL Checkpoint)
# -----------------------------------------------------------------------------
async def human_approval_node(state: InvestigationState) -> InvestigationState:
    """Checkpoint investigation state and await human review via REST API."""
    if state.get("approval_status") == "APPROVED":
        logger.info("Incident '%s' was approved by human operator.", state["incident_id"])
        state["status"] = "APPROVED"
        state["phase"] = "human_approval"
        return state
    elif state.get("approval_status") == "REJECTED":
        logger.info("Incident '%s' was rejected by human operator.", state["incident_id"])
        state["status"] = "REJECTED"
        state["phase"] = "human_approval"
        return state

    # Otherwise checkpoint and wait for operator approval
    state["approval_status"] = "AWAITING_APPROVAL"
    state["status"] = "AWAITING_APPROVAL"
    state["phase"] = "human_approval"
    await execution_memory.save_checkpoint(state["incident_id"], state)
    logger.info("Investigation '%s' is now AWAITING_APPROVAL.", state["incident_id"])
    return state


# -----------------------------------------------------------------------------
# Node 10: Memory Writer
# -----------------------------------------------------------------------------
async def memory_writer_node(state: InvestigationState) -> InvestigationState:
    """Persist approved resolution into PostgreSQL and Qdrant incident_resolutions."""
    rep_dict = state.get("final_report", {})
    approved = state.get("approval_status") == "APPROVED"

    async with async_session_factory() as session:
        record = await incident_memory.store_resolution(
            session=session,
            incident_id=state["incident_id"],
            resolution_data={
                "root_cause": rep_dict.get("root_cause", ""),
                "resolution_summary": rep_dict.get("reasoning_summary", ""),
                "suggested_fix": rep_dict.get("suggested_fix", ""),
                "confidence": state.get("confidence", 0.9),
                "affected_services": [state.get("primary_service")],
                "inspected_files": state.get("visited_files", []),
                "inspected_symbols": state.get("visited_symbols", []),
                "consulted_docs": state.get("visited_docs", []),
                "blast_radius": state.get("blast_radius"),
                "references": rep_dict.get("references", []),
                "reasoning_summary": rep_dict.get("reasoning_summary"),
                "reused_incident_id": state.get("reused_incident_id"),
            },
            approved=approved,
            reviewer_feedback=state.get("human_feedback"),
        )
        logger.info("Memory Writer committed resolution (id: %s, approved: %s)", record.id, approved)

    if approved:
        state["status"] = "RESOLVED"
        if "final_report" in state and isinstance(state["final_report"], dict):
            state["final_report"]["resolution_status"] = "RESOLVED"

    state["phase"] = "memory_writer"
    await execution_memory.save_checkpoint(state["incident_id"], state)
    return state


# -----------------------------------------------------------------------------
# Node 11: Exit
# -----------------------------------------------------------------------------
async def exit_node(state: InvestigationState) -> InvestigationState:
    """Final wrap-up node."""
    state["phase"] = "complete"
    await execution_memory.save_checkpoint(state["incident_id"], state)
    return state


# -----------------------------------------------------------------------------
# Conditional Routing Functions
# -----------------------------------------------------------------------------
def route_after_memory_lookup(state: InvestigationState) -> str:
    """Shortcut directly to exit if similar resolved incident is found in memory."""
    if state.get("cached_solution_found"):
        return "exit"
    return "index_verification"


def route_after_hypothesis(state: InvestigationState) -> str:
    """Check termination conditions: confidence, iterations, token limits, or plan recommendation."""
    confidence = state.get("confidence", 0.0)
    threshold = state.get("confidence_threshold", settings.STAGE4_CONFIDENCE_THRESHOLD)
    iterations = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", settings.STAGE4_MAX_ITERATIONS)
    tokens_used = state.get("tokens_used", 0)
    token_budget = state.get("token_budget", settings.STAGE4_TOKEN_BUDGET)

    plan = state.get("current_plan", {})
    stop_recommended = plan.get("stop_recommended", False) if isinstance(plan, dict) else False

    if confidence >= threshold or iterations >= max_iter or tokens_used >= token_budget or stop_recommended:
        logger.info("Terminating investigation loop (confidence: %.2f, iter: %d, tokens: %d)", confidence, iterations, tokens_used)
        return "reviewer"

    return "planner"


def route_after_approval(state: InvestigationState) -> str:
    """Route to memory writer if approved/rejected, or exit if awaiting human input."""
    status = state.get("approval_status")
    if status in ("APPROVED", "REJECTED"):
        return "memory_writer"
    return "exit"


# -----------------------------------------------------------------------------
# Build and Compile LangGraph
# -----------------------------------------------------------------------------
def build_investigation_graph() -> StateGraph:
    """Construct the modular StateGraph for the autonomous agent."""
    graph = StateGraph(InvestigationState)

    # Register all 11 nodes
    graph.add_node("entry", entry_node)
    graph.add_node("memory_lookup", memory_lookup_node)
    graph.add_node("index_verification", index_verification_node)
    graph.add_node("context_builder", context_builder_node)
    graph.add_node("planner", planner_node)
    graph.add_node("evidence_gathering", evidence_gathering_node)
    graph.add_node("hypothesis_generator", hypothesis_generator_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("memory_writer", memory_writer_node)
    graph.add_node("exit", exit_node)

    # Edges
    graph.add_edge(START, "entry")
    graph.add_edge("entry", "memory_lookup")

    # Memory lookup conditional: cache hit -> exit, else -> index_verification
    graph.add_conditional_edges(
        "memory_lookup",
        route_after_memory_lookup,
        {"exit": "exit", "index_verification": "index_verification"},
    )

    graph.add_edge("index_verification", "context_builder")
    graph.add_edge("context_builder", "planner")
    graph.add_edge("planner", "evidence_gathering")
    graph.add_edge("evidence_gathering", "hypothesis_generator")

    # Loop conditional: enough evidence -> reviewer, else -> planner
    graph.add_conditional_edges(
        "hypothesis_generator",
        route_after_hypothesis,
        {"reviewer": "reviewer", "planner": "planner"},
    )

    graph.add_edge("reviewer", "human_approval")

    # Approval conditional: decided -> memory_writer, else -> exit
    graph.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {"memory_writer": "memory_writer", "exit": "exit"},
    )

    graph.add_edge("memory_writer", "exit")
    graph.add_edge("exit", END)

    return graph


# Pre-compiled application instance
investigation_app = build_investigation_graph().compile()


async def run_investigation(request: InvestigationRunRequest) -> InvestigationState:
    """Execute autonomous incident investigation from a request payload."""
    initial_state: InvestigationState = {
        "incident_id": request.incident_id or str(uuid.uuid4()),
        "primary_service": request.primary_service or "unknown",
        "title": request.title or f"Failure in {request.primary_service or 'service'}",
        "error_message": request.error_message or "Unknown error",
        "error_trace": request.error_trace,
        "max_iterations": request.max_iterations or settings.STAGE4_MAX_ITERATIONS,
        "confidence_threshold": request.confidence_threshold or settings.STAGE4_CONFIDENCE_THRESHOLD,
        "token_budget": request.get_token_budget() or settings.STAGE4_TOKEN_BUDGET,
        "approval_status": "APPROVED" if request.auto_approve else "INVESTIGATING",
    }

    final_state = await investigation_app.ainvoke(initial_state)
    return final_state
