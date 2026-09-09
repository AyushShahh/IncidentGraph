"""Token-bounded context package synthesizer for the Stage 4 investigation agent.

Assembles deterministic, highly-relevant code snippets, symbol definitions,
and dependency topology strictly within configured token budgets.
"""
import re
from typing import Any, Dict, List, Optional

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.repository.schemas import (
    BlastRadiusResult,
    CodeSnippet,
    ContextPackage,
    SymbolDefinition,
)

logger = get_logger(__name__)

# Heuristic: 1 token is roughly 4 characters in code/text
CHARS_PER_TOKEN = 4


class ContextBuilder:
    """Deterministic context packager enforcing strict token budgeting."""

    def __init__(self, tools_instance: Optional[Any] = None) -> None:
        if tools_instance is None:
            from backend.repository.tools import get_repository_tools
            self.tools = get_repository_tools()
        else:
            self.tools = tools_instance

    async def build_context(
        self,
        service: str,
        incident_id: Optional[str] = None,
        error_trace: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        token_budget: Optional[int] = None,
    ) -> ContextPackage:
        """Synthesize a complete ContextPackage with strict token limits."""
        budget = token_budget or settings.STAGE3_MAX_CONTEXT_TOKENS
        char_budget = budget * CHARS_PER_TOKEN

        target_files: List[str] = list(file_paths) if file_paths else []
        snippets: List[CodeSnippet] = []
        symbols: List[SymbolDefinition] = []
        truncated = False

        # 1. Parse stack trace for files, line numbers, and symbols
        stack_locations = self._parse_stack_trace(error_trace) if error_trace else []
        for file_match, line_no in stack_locations:
            if file_match not in target_files:
                target_files.append(file_match)

        # 2. Extract code snippets around error lines (highest priority)
        for fpath, line_no in stack_locations:
            snippet_res = self.tools.read_lines(
                service=service,
                file_path=fpath,
                start_line=max(1, line_no - 15),
                end_line=line_no + 15,
            )
            if "content" in snippet_res:
                snippets.append(
                    CodeSnippet(
                        service_name=service,
                        file_path=fpath,
                        start_line=snippet_res["start_line"],
                        end_line=snippet_res["end_line"],
                        content=snippet_res["content"],
                        reason=f"Stack trace error site around line {line_no}",
                    )
                )

        # If specific target_files requested without line numbers, read primary file excerpt
        if not snippets and target_files:
            first_file = target_files[0]
            f_res = self.tools.read_file(service=service, file_path=first_file, max_lines=60)
            if "content" in f_res:
                snippets.append(
                    CodeSnippet(
                        service_name=service,
                        file_path=first_file,
                        start_line=1,
                        end_line=f_res["lines_returned"],
                        content=f_res["content"],
                        reason="Primary service file entry point",
                    )
                )

        # 3. Collect symbol definitions relevant to service and error
        svc_symbols = self.tools.symbol_index.search_symbols("", service=service, limit=30)
        # Prioritize symbols mentioned in stack trace
        if error_trace:
            for sym in svc_symbols:
                if sym.name in error_trace:
                    if sym not in symbols:
                        symbols.append(sym)

        # Add remaining symbols up to limit
        for sym in svc_symbols:
            if len(symbols) >= 15:
                break
            if sym not in symbols:
                symbols.append(sym)

        # 4. Dependency graph and blast radius
        dep_summary = self.tools.lookup_dependencies(service)
        blast_radius_dict = self.tools.get_blast_radius(service)
        blast_radius = BlastRadiusResult.model_validate(blast_radius_dict)

        # 5. Semantic code search for additional relevant chunks if budget permits
        if error_trace:
            # Extract first line of error or exception name for search
            err_line = error_trace.strip().splitlines()[-1] if error_trace.strip() else service
            search_hits = await self.tools.search_code(query=err_line[:120], service=service, limit=3)
            for hit in search_hits:
                # Avoid duplicate files already covered
                if not any(s.file_path == hit["file_path"] and s.start_line == hit["start_line"] for s in snippets):
                    snippets.append(
                        CodeSnippet(
                            service_name=hit["service"],
                            file_path=hit["file_path"],
                            start_line=hit["start_line"],
                            end_line=hit["end_line"],
                            content=hit["content"],
                            reason="Semantic search match for error pattern",
                        )
                    )

        # 6. Strict token budget enforcement
        # Budget prioritization:
        # P1: Error stack snippets
        # P2: Dependency summary & Blast Radius
        # P3: Symbols
        # P4: Additional semantic snippets
        current_chars = 0

        # Calculate base overhead (dependency summary, blast radius)
        dep_chars = len(str(dep_summary)) + len(str(blast_radius_dict))
        current_chars += dep_chars

        final_snippets: List[CodeSnippet] = []
        for snip in snippets:
            snip_chars = len(snip.content)
            if current_chars + snip_chars <= char_budget:
                final_snippets.append(snip)
                current_chars += snip_chars
            else:
                truncated = True

        final_symbols: List[SymbolDefinition] = []
        for sym in symbols:
            sym_chars = len(sym.name) + len(sym.signature or "") + len(sym.docstring or "")
            if current_chars + sym_chars <= char_budget:
                final_symbols.append(sym)
                current_chars += sym_chars
            else:
                truncated = True

        estimated_tokens = max(1, current_chars // CHARS_PER_TOKEN)

        return ContextPackage(
            incident_id=incident_id,
            primary_service=service,
            target_files=target_files,
            code_snippets=final_snippets,
            symbols=final_symbols,
            dependency_summary=dep_summary,
            blast_radius=blast_radius,
            estimated_tokens=estimated_tokens,
            token_budget=budget,
            truncated=truncated,
        )

    @staticmethod
    def _parse_stack_trace(error_trace: str) -> List[tuple[str, int]]:
        """Extract (relative_file_path, line_number) tuples from traceback text."""
        locations: List[tuple[str, int]] = []
        # Pattern: File ".../service/main.py", line 42
        pattern = r'File\s+["\']([^"\']+)["\'],\s+line\s+(\d+)'
        matches = re.findall(pattern, error_trace)

        for raw_path, line_str in matches:
            line_no = int(line_str)
            # Normalize path: extract filename or relative path
            clean_path = raw_path.replace("\\", "/")
            # If path contains /app/ or /services/
            if "/services/" in clean_path:
                clean_path = clean_path.split("/services/", 1)[1]
                # remove service name prefix if present (e.g. gateway/main.py -> main.py)
                parts = clean_path.split("/", 1)
                if len(parts) > 1:
                    clean_path = parts[1]
            elif "/app/" in clean_path:
                clean_path = clean_path.split("/app/", 1)[1]
            else:
                clean_path = Path(clean_path).name

            if (clean_path, line_no) not in locations:
                locations.append((clean_path, line_no))

        return locations
