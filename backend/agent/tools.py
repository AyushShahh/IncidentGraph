"""Stage 4 Tool Dispatcher delegating to Stage 3 Repository Intelligence tools."""
import asyncio
from typing import Any, Dict, Optional

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.repository.tools import get_repository_tools

logger = get_logger(__name__)


class AgentToolDispatcher:
    """Safe, timeout-bounded dispatcher for Stage 3 repository retrieval tools."""

    def __init__(self, timeout: Optional[float] = None) -> None:
        self.timeout = timeout or settings.STAGE4_TOOL_TIMEOUT_SECONDS
        self.tools = get_repository_tools()

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Execute a Stage 3 tool by name with timeout enforcement."""
        clean_tool = tool_name.strip().lower()

        # Helper to execute sync or async method safely
        async def _invoke():
            if clean_tool in ("read_lines", "get_file_lines"):
                return self.tools.read_lines(
                    service=args.get("service", ""),
                    file_path=args.get("file_path", ""),
                    start_line=int(args.get("start_line", 1)),
                    end_line=int(args.get("end_line", 30)),
                )
            elif clean_tool in ("read_file", "get_file"):
                return self.tools.read_file(
                    service=args.get("service", ""),
                    file_path=args.get("file_path", ""),
                    max_lines=int(args.get("max_lines", 60)),
                )
            elif clean_tool in ("find_symbol", "lookup_symbol"):
                return self.tools.find_symbol(
                    symbol_name=args.get("symbol_name", ""),
                    service=args.get("service"),
                )
            elif clean_tool in ("search_code", "semantic_search"):
                return await self.tools.search_code(
                    query=args.get("query", ""),
                    service=args.get("service"),
                    limit=int(args.get("limit", 3)),
                )
            elif clean_tool in ("find_callers", "get_callers"):
                return self.tools.find_callers(service=args.get("service", ""))
            elif clean_tool in ("find_dependencies", "get_dependencies"):
                return self.tools.find_dependencies(service=args.get("service", ""))
            elif clean_tool in ("get_blast_radius", "blast_radius"):
                return self.tools.get_blast_radius(service=args.get("service", ""))
            elif clean_tool in ("get_service_routes", "list_routes"):
                return self.tools.get_service_routes(service=args.get("service", ""))
            elif clean_tool in ("read_config", "get_config"):
                return self.tools.read_config(
                    service=args.get("service", ""),
                    config_name=args.get("config_name", ""),
                )
            elif clean_tool in ("list_directory", "list_files"):
                return self.tools.list_directory(
                    service=args.get("service", ""),
                    relative_path=args.get("relative_path", ""),
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
