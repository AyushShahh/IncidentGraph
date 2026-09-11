"""Context Manager responsible for token budgeting, tool output condensation, and working memory pruning."""
import re
from typing import Any, Dict, List, Optional, Set

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

CHARS_PER_TOKEN = 4


class ContextManager:
    """Aggressively optimizes and prunes working context to minimize LLM token consumption."""

    def __init__(self, token_budget: Optional[int] = None) -> None:
        self.max_tokens = token_budget or settings.STAGE4_TOKEN_BUDGET

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count using 4 chars per token heuristic."""
        if not text:
            return 0
        return max(1, len(text) // CHARS_PER_TOKEN)

    def summarize_tool_output(self, tool_name: str, raw_output: Any, max_token_limit: int = 250) -> Dict[str, Any]:
        """Condense verbose tool outputs into high-signal, compact summaries."""
        if isinstance(raw_output, dict):
            if "error" in raw_output:
                return {
                    "source_tool": tool_name,
                    "finding_summary": f"Tool error: {raw_output['error']}",
                    "code_snippet": None,
                    "relevance": "error",
                }

        # Case 1: read_lines or read_file
        if tool_name in ("read_lines", "read_file") and isinstance(raw_output, dict):
            fpath = raw_output.get("file_path", "")
            content = raw_output.get("content", "")
            lines = content.splitlines()

            # Keep at most 12 critical lines around the center of the slice
            if len(lines) > 14:
                condensed_lines = lines[:12] + [f"    ... [{len(lines) - 12} lines omitted]"]
            else:
                condensed_lines = lines

            snippet = "\n".join(condensed_lines)
            start_l = raw_output.get("start_line", 1)
            end_l = raw_output.get("end_line", start_l + len(lines))

            return {
                "source_tool": tool_name,
                "file_path": fpath,
                "line_range": f"{start_l}-{end_l}",
                "code_snippet": snippet,
                "finding_summary": f"Inspected {fpath}:{start_l}-{end_l} ({len(lines)} lines)",
                "relevance": "source_code",
            }

        # Case 2: search_code
        if tool_name == "search_code" and isinstance(raw_output, list):
            if not raw_output:
                return {
                    "source_tool": tool_name,
                    "finding_summary": "Zero semantic matches found.",
                    "code_snippet": None,
                    "relevance": "empty",
                }

            # Prioritize code chunks (.py) over documentation if present
            code_hits = [h for h in raw_output if str(h.get("file_path", "")).endswith(".py")]
            top_hit = code_hits[0] if code_hits else raw_output[0]
            fpath = top_hit.get("file_path", "")
            raw_c = top_hit.get("content", "").splitlines()
            snippet = "\n".join(raw_c[:8])
            matched_locs = [f"{h.get('file_path')}:{h.get('start_line')}" for h in raw_output[:3]]
            return {
                "source_tool": tool_name,
                "file_path": fpath,
                "line_range": f"{top_hit.get('start_line')}-{top_hit.get('end_line')}",
                "code_snippet": snippet,
                "finding_summary": f"Found {len(raw_output)} match(es) [{', '.join(matched_locs)}], top match in {fpath} (symbols: {top_hit.get('symbols', [])}, score: {top_hit.get('similarity_score', 0)})",
                "relevance": "code_search",
            }

        # Case 3: find_symbol
        if tool_name == "find_symbol" and isinstance(raw_output, list):
            if not raw_output:
                return {
                    "source_tool": tool_name,
                    "finding_summary": "Symbol not found in symbol table.",
                    "code_snippet": None,
                    "relevance": "empty",
                }
            match = raw_output[0]
            return {
                "source_tool": tool_name,
                "file_path": match.get("file_path"),
                "line_range": f"{match.get('start_line')}-{match.get('end_line')}",
                "code_snippet": match.get("signature"),
                "finding_summary": f"Symbol '{match.get('name')}' ({match.get('symbol_type')}) in {match.get('file_path')}:{match.get('start_line')}",
                "relevance": "symbol_definition",
            }

        # Case 4: Blast radius or dependencies
        if tool_name in ("get_blast_radius", "lookup_dependencies", "find_callers", "find_dependencies"):
            if isinstance(raw_output, dict):
                summary = raw_output.get("summary") or f"Direct callers: {raw_output.get('direct_callers', [])}"
                return {
                    "source_tool": tool_name,
                    "finding_summary": summary,
                    "code_snippet": None,
                    "relevance": "topology",
                }
            elif isinstance(raw_output, list):
                return {
                    "source_tool": tool_name,
                    "finding_summary": f"Services: {raw_output}",
                    "code_snippet": None,
                    "relevance": "topology",
                }

        # Case 5: Service routes
        if tool_name in ("get_service_routes", "list_routes") and isinstance(raw_output, list):
            if not raw_output:
                return {
                    "source_tool": tool_name,
                    "finding_summary": "No HTTP routes registered for this service.",
                    "code_snippet": None,
                    "relevance": "routes",
                }
            routes_summary = ", ".join([f"{r.get('method', 'ANY')} {r.get('path', '/')}" for r in raw_output[:8]])
            return {
                "source_tool": tool_name,
                "finding_summary": f"Exposes {len(raw_output)} route(s): [{routes_summary}]",
                "code_snippet": None,
                "relevance": "routes",
            }

        # Case 6: Config files
        if tool_name in ("read_config", "get_config") and isinstance(raw_output, dict):
            cfg_name = raw_output.get("config_name", "config")
            content = raw_output.get("content", "")
            lines = content.splitlines()
            snippet = "\n".join(lines[:12])
            return {
                "source_tool": tool_name,
                "file_path": cfg_name,
                "finding_summary": f"Inspected config '{cfg_name}' ({len(lines)} lines)",
                "code_snippet": snippet,
                "relevance": "configuration",
            }

        # Case 7: Directory listing
        if tool_name in ("list_directory", "list_files") and isinstance(raw_output, dict):
            entries = raw_output.get("entries", [])
            names = [f"{e.get('name')}{'/' if e.get('is_directory') else ''}" for e in entries[:12]]
            return {
                "source_tool": tool_name,
                "finding_summary": f"Directory '{raw_output.get('path', '.')}' has {len(entries)} items: {', '.join(names)}",
                "code_snippet": None,
                "relevance": "directory_listing",
            }

        # Generic fallback
        raw_str = str(raw_output)
        if len(raw_str) > 400:
            raw_str = raw_str[:400] + "... [truncated]"
        return {
            "source_tool": tool_name,
            "finding_summary": raw_str,
            "code_snippet": None,
            "relevance": "general",
        }

    def is_duplicate_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        visited_files: Set[str],
        visited_symbols: Set[str],
        visited_queries: Optional[Set[str]] = None,
        visited_ranges: Optional[Set[str]] = None,
    ) -> bool:
        """Prevent agent from invoking identical tool operations repeatedly.

        Tools may be called multiple times during an investigation as long as 
        the target or arguments (e.g. line ranges, symbols, queries) differ.
        """
        clean_tool = tool_name.strip().lower().replace("-", "_").replace(" ", "_")

        if clean_tool in ("read_lines", "get_file_lines", "inspect_lines"):
            if visited_ranges is not None:
                fpath = args.get("file_path") or args.get("filepath") or args.get("path") or ""
                start_l = args.get("start_line") or args.get("start")
                end_l = args.get("end_line") or args.get("end")
                if start_l is not None and end_l is not None:
                    range_key = f"{fpath}:{start_l}-{end_l}"
                    return range_key in visited_ranges
            return False

        if clean_tool in ("read_file", "get_file"):
            fpath = args.get("file_path") or args.get("filepath") or args.get("path") or ""
            return fpath in visited_files

        if clean_tool in ("find_symbol", "lookup_symbol"):
            sym = args.get("symbol_name") or args.get("symbol") or args.get("name") or ""
            return sym in visited_symbols if sym else False

        if clean_tool in ("search_code", "semantic_search") and visited_queries is not None:
            q = (args.get("query") or args.get("q") or "").strip().lower()
            return q in visited_queries if q else False

        return False

    def build_working_context_prompt(self, state: Dict[str, Any]) -> str:
        """Format an ultra-lean, token-bounded context prompt for Planner and Hypothesis nodes."""
        blocks = []

        # 1. Incident Target & Core Signal (~80 tokens)
        blocks.append(
            f"### INCIDENT\n"
            f"Service: {state.get('primary_service')}\n"
            f"Title: {state.get('title')}\n"
            f"Error: {state.get('error_message')}"
        )

        error_trace = state.get("error_trace")
        if error_trace:
            # Extract the last 6 lines of traceback
            trace_lines = [l for l in error_trace.strip().splitlines() if l.strip()]
            recent_trace = "\n".join(trace_lines[-6:])
            blocks.append(f"### ERROR TRACE (TAIL)\n```\n{recent_trace}\n```")

        # 2. Accumulated Verified Evidence (~200 tokens)
        evidence_list = state.get("evidence", [])
        if evidence_list:
            ev_blocks = ["### VERIFIED EVIDENCE ITEMS"]
            for i, ev in enumerate(evidence_list[-4:], 1):  # Keep latest 4 evidence items
                snippet = ev.get("code_snippet")
                snippet_str = f"\n```python\n{snippet}\n```" if snippet else ""
                ev_blocks.append(f"[{i}] ({ev.get('source_tool')}): {ev.get('finding_summary')}{snippet_str}")
            blocks.append("\n".join(ev_blocks))

        # 3. Current Working Hypothesis if present (~100 tokens)
        hypo = state.get("hypothesis")
        if hypo and isinstance(hypo, dict):
            blocks.append(
                f"### CURRENT HYPOTHESIS\n"
                f"Root Cause: {hypo.get('root_cause_statement')}\n"
                f"Mechanism: {hypo.get('failure_mechanism')}\n"
                f"Confidence: {hypo.get('confidence', 0.0)}"
            )

        # 4. Visited tracking (~30 tokens)
        visited_f = state.get("visited_files", [])
        if visited_f:
            blocks.append(f"Already inspected files: {', '.join(visited_f)}")

        # 5. Discovered service files if available
        service = state.get("primary_service")
        if service:
            try:
                from backend.repository.indexer import get_repository_indexer
                indexer = get_repository_indexer()
                svc_path = indexer.get_service_path(service)
                if svc_path and svc_path.exists():
                    py_files = [p.name for p in svc_path.glob("*.py")]
                    if py_files:
                        blocks.append(f"Available Python files in service '{service}': {', '.join(sorted(py_files))}")
            except Exception:
                pass

        result = "\n\n".join(blocks)
        logger.debug("Assembled working context prompt (~%d tokens)", self.estimate_tokens(result))
        return result


# Global singleton instance
context_manager = ContextManager()
