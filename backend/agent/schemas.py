"""Pydantic schemas and state definitions for Stage 4 Autonomous Investigation Agent."""
from typing import Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel, Field


class ToolAction(BaseModel):
    """Specific tool invocation planned by the agent."""
    tool_name: str = Field(..., description="Name of the Stage 3 retrieval tool to invoke")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool")
    rationale: str = Field(..., description="Concise rationale for why this tool was selected")


class InvestigationPlan(BaseModel):
    """Next single-step tactical investigation plan produced by the Planner."""
    objective: str = Field(..., description="Specific goal of this investigation step")
    target_tool: ToolAction = Field(..., description="Tool to run next")
    expected_finding: str = Field(..., description="What evidence this action is expected to confirm or refute")
    stop_recommended: bool = Field(default=False, description="True if sufficient evidence is already collected")
    stop_reason: Optional[str] = Field(default=None, description="Reason for stopping investigation early")


class EvidenceItem(BaseModel):
    """Pruned, verified piece of code or architectural evidence."""
    evidence_id: str
    source_tool: str
    file_path: Optional[str] = None
    line_range: Optional[str] = None
    code_snippet: Optional[str] = None
    finding_summary: str
    relevance: str


class Hypothesis(BaseModel):
    """Working root cause hypothesis synthesized by the agent."""
    root_cause_statement: str = Field(..., description="Clear, succinct diagnosis of the bug or failure")
    failure_mechanism: str = Field(..., description="Step-by-step causal chain leading to the incident")
    affected_component: str = Field(..., description="Specific file, function, or configuration at fault")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    remaining_doubts: List[str] = Field(default_factory=list, description="Any unverified assumptions or missing evidence")
    has_enough_evidence: bool = Field(default=False, description="True if evidence is sufficient to draft fix")


class ReviewResult(BaseModel):
    """Adversarial critique of the hypothesis and proposed fix."""
    is_valid: bool = Field(..., description="Whether the hypothesis is logically sound and supported by evidence")
    critique: str = Field(..., description="Detailed adversarial critique pointing out potential flaws or regressions")
    verified_evidence: List[str] = Field(default_factory=list, description="List of evidence points that were verified")
    approved_for_fix: bool = Field(..., description="Whether the agent is authorized to proceed to human approval")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Audited confidence score")


class ReportSynthesis(BaseModel):
    """Structured output model for final report synthesis generation."""
    root_cause: str = Field(..., description="Authoritative explanation of the bug and why it triggered")
    suggested_fix: str = Field(..., description="Exact code diff or python replacement lines resolving the bug")
    blast_radius: Optional[Dict[str, Any]] = Field(default=None, description="Blast radius assessment")
    references: List[str] = Field(default_factory=list, description="Relevant files, routes, or documentation referenced")
    reasoning_summary: str = Field(..., description="Step-by-step reasoning linking the error signal to the code flaw")


class FinalReport(BaseModel):
    """Comprehensive, production-grade root cause analysis and resolution proposal."""
    incident_id: str
    primary_service: str
    root_cause: str
    evidence: List[EvidenceItem] = Field(default_factory=list)
    inspected_files: List[str] = Field(default_factory=list)
    inspected_symbols: List[str] = Field(default_factory=list)
    consulted_docs: List[str] = Field(default_factory=list)
    blast_radius: Optional[Dict[str, Any]] = None
    confidence: float = 0.90
    suggested_fix: str
    references: List[str] = Field(default_factory=list)
    reasoning_summary: str
    reused_incident_id: Optional[str] = None
    resolution_status: str = "AWAITING_APPROVAL"


class InvestigationRunRequest(BaseModel):
    """Payload to trigger an autonomous incident investigation."""
    incident_id: Optional[str] = None
    primary_service: Optional[str] = None
    title: Optional[str] = None
    error_message: Optional[str] = None
    error_trace: Optional[str] = None
    max_iterations: Optional[int] = None
    confidence_threshold: Optional[float] = None
    token_budget: Optional[int] = None
    max_tokens: Optional[int] = None
    auto_approve: bool = False

    def get_token_budget(self) -> Optional[int]:
        return self.max_tokens or self.token_budget


class InvestigationApprovalRequest(BaseModel):
    """Payload to submit human review on an investigated incident."""
    approved: bool
    reviewer_feedback: Optional[str] = None


class InvestigationState(TypedDict, total=False):
    """State object passed between LangGraph nodes during investigation."""
    incident_id: str
    primary_service: str
    title: str
    error_message: str
    error_trace: Optional[str]
    initial_context: Optional[Dict[str, Any]]
    current_plan: Optional[Dict[str, Any]]
    evidence: List[Dict[str, Any]]
    hypothesis: Optional[Dict[str, Any]]
    visited_files: List[str]
    visited_symbols: List[str]
    visited_docs: List[str]
    iteration_count: int
    max_iterations: int
    confidence: float
    confidence_threshold: float
    token_budget: int
    tokens_used: int
    review_result: Optional[Dict[str, Any]]
    final_report: Optional[Dict[str, Any]]
    cached_solution_found: bool
    reused_incident_id: Optional[str]
    approval_status: str  # "AWAITING_APPROVAL", "APPROVED", "REJECTED"
    human_feedback: Optional[str]
    phase: str
    status: str
