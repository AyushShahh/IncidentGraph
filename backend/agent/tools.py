"""Stage 4 Tool Dispatcher delegating to Stage 3 Repository Intelligence tools."""
import asyncio
from typing import Any, Dict, Optional

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.repository.tools import get_repository_tools

logger = get_logger(__name__)


def _to_int(val: Any, default: int) -> int:
    """Safely convert value to integer, handling string ranges (e.g. '88-118')."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return int(val)
    val_str = str(val).strip()
    if "-" in val_str:
        val_str = val_str.split("-")[0].strip()
    try:
        return int(val_str)
    except (ValueError, TypeError):
        return default


class AgentToolDispatcher:
    """Safe, timeout-bounded dispatcher for Stage 3 repository retrieval tools."""

    def __init__(self, timeout: Optional[float] = None) -> None:
        self.timeout = timeout or settings.STAGE4_TOOL_TIMEOUT_SECONDS
        self.tools = get_repository_tools()

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Execute a Stage 3 tool by name with timeout enforcement."""
        clean_tool = tool_name.strip().lower().replace("-", "_").replace(" ", "_")
        args = args or {}

        # Extract common aliases
        svc = args.get("service") or args.get("service_name") or ""
        file_p = args.get("file_path") or args.get("filepath") or args.get("path") or ""

        # Handle line number aliases for read_lines
        start_l = args.get("start_line") or args.get("start")
        end_l = args.get("end_line") or args.get("end")
        if start_l is None and args.get("line_number") is not None:
            ln = _to_int(args.get("line_number"), 1)
            start_l = max(1, ln - 15)
            end_l = ln + 15
        elif start_l is not None and isinstance(start_l, str) and "-" in start_l and end_l is None:
            parts = start_l.split("-")
            start_l = _to_int(parts[0], 1)
            end_l = _to_int(parts[1], start_l + 30)

        # Helper to execute sync or async method safely
        async def _invoke():
            if clean_tool in ("read_lines", "get_file_lines", "inspect_lines"):
                return self.tools.read_lines(
                    service=svc,
                    file_path=file_p,
                    start_line=_to_int(start_l, 1),
                    end_line=_to_int(end_l, 30),
                )
            elif clean_tool in ("read_file", "get_file"):
                return self.tools.read_file(
                    service=svc,
                    file_path=file_p,
                    max_lines=_to_int(args.get("max_lines"), 60),
                )
            elif clean_tool in ("find_symbol", "lookup_symbol"):
                sym = args.get("symbol_name") or args.get("symbol") or args.get("name") or ""
                return self.tools.find_symbol(
                    symbol_name=sym,
                    service=svc or None,
                )
            elif clean_tool in ("search_code", "semantic_search"):
                q = args.get("query") or args.get("q") or ""
                return await self.tools.search_code(
                    query=q,
                    service=svc or None,
                    limit=_to_int(args.get("limit"), 3),
                )
            elif clean_tool in ("find_callers", "get_callers"):
                return self.tools.find_callers(service=svc)
            elif clean_tool in ("find_dependencies", "get_dependencies"):
                return self.tools.find_dependencies(service=svc)
            elif clean_tool in ("get_blast_radius", "blast_radius"):
                return self.tools.get_blast_radius(service=svc)
            elif clean_tool in ("get_service_routes", "list_routes"):
                return self.tools.get_service_routes(service=svc)
            elif clean_tool in ("read_config", "get_config"):
                cfg = args.get("config_name") or args.get("config") or args.get("name") or ""
                return self.tools.read_config(
                    service=svc,
                    config_name=cfg,
                )
            elif clean_tool in ("list_directory", "list_files"):
                rel_p = args.get("relative_path") or args.get("path") or ""
                return self.tools.list_directory(
                    service=svc,
                    relative_path=rel_p,
                )
            else:
                return {"error": f"Unknown tool '{tool_name}'"}

        try:
            return await asyncio.wait_for(_invoke(), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.error("Tool execution '%s' timed out after %ss", tool_name, self.timeout)
            return {"error": f"Tool '{tool_name}' timed out after {self.timeout}s"}
        except Exception as exc:
            logger.error("Tool execution '%s' failed: %s", tool_name, exc)
            return {"error": f"Tool execution failed: {exc}"}


# Global singleton instance
agent_tool_dispatcher = AgentToolDispatcher()
