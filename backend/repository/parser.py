"""AST-based code parser, symbol extractor, outbound call detector, and document chunker.

Completely deterministic: uses Python's standard `ast` module and regexes.
No external LLM or heuristics.
"""
import ast
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.repository.schemas import (
    ChunkType,
    CodeChunk,
    RouteInfo,
    SymbolDefinition,
    SymbolType,
)

logger = get_logger(__name__)

HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}


class OutboundCallInfo:
    """Discovered outbound network or event call within code."""

    def __init__(
        self,
        caller_service: str,
        caller_file: str,
        line_no: int,
        call_type: str,  # "http", "kafka", "redis"
        target_service_hint: Optional[str] = None,
        target_url_or_path: Optional[str] = None,
        http_method: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> None:
        self.caller_service = caller_service
        self.caller_file = caller_file
        self.line_no = line_no
        self.call_type = call_type
        self.target_service_hint = target_service_hint
        self.target_url_or_path = target_url_or_path
        self.http_method = http_method
        self.topic = topic


class CodeParser:
    """Parses source code into structured symbols, route endpoints, and outbound interactions."""

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name

    def parse_python_file(
        self,
        file_path_str: str,
        content: str,
    ) -> Tuple[List[SymbolDefinition], List[OutboundCallInfo], List[CodeChunk]]:
        """Parse a Python source file into symbols, outbound dependencies, and code chunks."""
        try:
            tree = ast.parse(content, filename=file_path_str)
        except SyntaxError as exc:
            logger.warning("SyntaxError parsing %s in %s: %s", file_path_str, self.service_name, exc)
            fallback_chunks = self._chunk_plain_text(file_path_str, content, ChunkType.CODE)
            return [], [], fallback_chunks

        lines = content.splitlines()
        symbols: List[SymbolDefinition] = []
        outbound_calls: List[OutboundCallInfo] = []

        # 1. Inspect top-level environment variable URL definitions
        env_url_map = self._extract_env_service_urls(tree)

        # 2. Extract symbols & routes
        for node in tree.body:
            # Top-level Functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sym, route = self._parse_function_node(node, file_path_str, lines)
                symbols.append(sym)
            # Classes
            elif isinstance(node, ast.ClassDef):
                sym = self._parse_class_node(node, file_path_str, lines)
                symbols.append(sym)
                # Methods inside class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_sym, _ = self._parse_function_node(
                            item, file_path_str, lines, parent_class=node.name
                        )
                        symbols.append(method_sym)
            # Constants
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        end_line = getattr(node, "end_lineno", node.lineno)
                        symbols.append(
                            SymbolDefinition(
                                name=target.id,
                                symbol_type=SymbolType.CONSTANT,
                                service_name=self.service_name,
                                file_path=file_path_str,
                                start_line=node.lineno,
                                end_line=end_line,
                                signature=f"{target.id} = ...",
                                docstring=None,
                            )
                        )

        # 3. Extract outbound HTTP / Kafka / Redis calls via AST walk
        outbound_calls = self._extract_outbound_calls(tree, file_path_str, env_url_map)

        # 4. Generate granular code chunks
        chunks = self._chunk_python_file(file_path_str, content, lines, tree, symbols)

        return symbols, outbound_calls, chunks

    def parse_markdown_file(self, file_path_str: str, content: str) -> List[CodeChunk]:
        """Chunk markdown documentation by section headers."""
        lines = content.splitlines()
        chunks: List[CodeChunk] = []
        current_header = "Introduction"
        current_lines: List[str] = []
        start_line = 1

        for i, line in enumerate(lines, 1):
            if re.match(r"^#{1,3}\s+", line):
                if current_lines:
                    chunk_text = "\n".join(current_lines).strip()
                    if chunk_text:
                        chunks.append(
                            CodeChunk(
                                chunk_id=f"{self.service_name}:{file_path_str}:{start_line}",
                                service_name=self.service_name,
                                file_path=file_path_str,
                                start_line=start_line,
                                end_line=i - 1,
                                chunk_type=ChunkType.DOC,
                                content=chunk_text,
                                symbol_names=[current_header],
                                token_estimate=max(1, len(chunk_text) // 4),
                            )
                        )
                current_header = line.strip("# \t")
                current_lines = [line]
                start_line = i
            else:
                current_lines.append(line)

        if current_lines:
            chunk_text = "\n".join(current_lines).strip()
            if chunk_text:
                chunks.append(
                    CodeChunk(
                        chunk_id=f"{self.service_name}:{file_path_str}:{start_line}",
                        service_name=self.service_name,
                        file_path=file_path_str,
                        start_line=start_line,
                        end_line=len(lines),
                        chunk_type=ChunkType.DOC,
                        content=chunk_text,
                        symbol_names=[current_header],
                        token_estimate=max(1, len(chunk_text) // 4),
                    )
                )

        return chunks if chunks else self._chunk_plain_text(file_path_str, content, ChunkType.DOC)

    def parse_config_file(self, file_path_str: str, content: str) -> List[CodeChunk]:
        """Chunk configuration or dependency files."""
        return self._chunk_plain_text(file_path_str, content, ChunkType.CONFIG)

    # -------------------------------------------------------------------------
    # Internal AST helpers
    # -------------------------------------------------------------------------

    def _parse_function_node(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_path_str: str,
        lines: List[str],
        parent_class: Optional[str] = None,
    ) -> Tuple[SymbolDefinition, Optional[RouteInfo]]:
        """Extract function metadata, docstring, signature, and FastAPI route annotations."""
        end_line = getattr(node, "end_lineno", node.lineno)
        is_async = isinstance(node, ast.AsyncFunctionDef)

        sym_type = SymbolType.METHOD if parent_class else (
            SymbolType.ASYNC_FUNCTION if is_async else SymbolType.FUNCTION
        )
        display_name = f"{parent_class}.{node.name}" if parent_class else node.name

        docstring = ast.get_docstring(node)

        # Reconstruct signature from first line(s)
        sig_line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
        route_info = self._extract_route_info(node)
        if route_info:
            sym_type = SymbolType.ROUTE

        sym = SymbolDefinition(
            name=display_name,
            symbol_type=sym_type,
            service_name=self.service_name,
            file_path=file_path_str,
            start_line=node.lineno,
            end_line=end_line,
            signature=sig_line,
            docstring=docstring,
            route_info=route_info,
        )
        return sym, route_info

    def _parse_class_node(
        self,
        node: ast.ClassDef,
        file_path_str: str,
        lines: List[str],
    ) -> SymbolDefinition:
        """Extract class definition metadata."""
        end_line = getattr(node, "end_lineno", node.lineno)
        docstring = ast.get_docstring(node)
        sig_line = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""

        return SymbolDefinition(
            name=node.name,
            symbol_type=SymbolType.CLASS,
            service_name=self.service_name,
            file_path=file_path_str,
            start_line=node.lineno,
            end_line=end_line,
            signature=sig_line,
            docstring=docstring,
        )

    def _extract_route_info(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> Optional[RouteInfo]:
        """Detect FastAPI / Starlette / Flask route decorators (e.g. @app.get('/path'))."""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                method_candidate = decorator.func.attr.upper()
                if method_candidate in HTTP_METHODS:
                    # Path argument is typically the first positional argument
                    path = ""
                    if decorator.args and isinstance(decorator.args[0], ast.Constant):
                        path = str(decorator.args[0].value)
                    elif decorator.args and isinstance(decorator.args[0], ast.Str):
                        path = decorator.args[0].s

                    if path:
                        # Optional summary or response_model from kwargs
                        summary = None
                        response_model = None
                        for kw in decorator.keywords:
                            if kw.arg == "summary" and isinstance(kw.value, (ast.Constant, ast.Str)):
                                summary = getattr(kw.value, "value", getattr(kw.value, "s", None))
                            elif kw.arg == "response_model":
                                if isinstance(kw.value, ast.Name):
                                    response_model = kw.value.id

                        return RouteInfo(
                            method=method_candidate,
                            path=path,
                            summary=summary,
                            response_model=response_model,
                        )
        return None

    def _extract_env_service_urls(self, tree: ast.AST) -> dict[str, str]:
        """Extract environment variable URL defaults, e.g. ORDERS_SERVICE_URL = os.getenv(..., 'http://orders:8002')."""
        env_map: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                        # Detect os.getenv("FOO_SERVICE_URL", "http://foo:8000")
                        func = node.value.func
                        if (
                            isinstance(func, ast.Attribute)
                            and func.attr in ("getenv", "get")
                            and len(node.value.args) >= 2
                        ):
                            default_arg = node.value.args[1]
                            if isinstance(default_arg, (ast.Constant, ast.Str)):
                                val = getattr(default_arg, "value", getattr(default_arg, "s", ""))
                                if isinstance(val, str) and ("http://" in val or "https://" in val):
                                    env_map[target.id] = val
        return env_map

    def _extract_outbound_calls(
        self,
        tree: ast.AST,
        file_path_str: str,
        env_url_map: dict[str, str],
    ) -> List[OutboundCallInfo]:
        """Detect outbound HTTP, Kafka, and Redis calls via AST traversal."""
        calls: List[OutboundCallInfo] = []

        # Collect decorator call nodes so @app.get / @app.post are never treated as outbound calls
        decorator_calls = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for dec in n.decorator_list:
                    if isinstance(dec, ast.Call):
                        decorator_calls.add(dec)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node in decorator_calls:
                continue

            lineno = getattr(node, "lineno", 0)

            # 1. Detect HTTP client calls (http_client.get, http_client.post, httpx.get, etc.)
            if isinstance(node.func, ast.Attribute):
                caller_obj = node.func.value
                if isinstance(caller_obj, ast.Name) and caller_obj.id in ("app", "router", "api_router"):
                    continue

                attr_name = node.func.attr.lower()
                if attr_name in ("get", "post", "put", "delete", "patch", "request"):
                    target_url, target_hint = self._resolve_target_url(
                        node.args, env_url_map, keywords=node.keywords
                    )
                    if target_url or target_hint:
                        calls.append(
                            OutboundCallInfo(
                                caller_service=self.service_name,
                                caller_file=file_path_str,
                                line_no=lineno,
                                call_type="http",
                                target_service_hint=target_hint,
                                target_url_or_path=target_url,
                                http_method=attr_name.upper(),
                            )
                        )

            # 2. Detect Kafka producer publishes
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("send_and_wait", "send", "produce"):
                topic = None
                if node.args:
                    if isinstance(node.args[0], (ast.Constant, ast.Str)):
                        topic = getattr(node.args[0], "value", getattr(node.args[0], "s", None))
                    elif isinstance(node.args[0], ast.Attribute):
                        topic = node.args[0].attr
                for kw in node.keywords:
                    if kw.arg == "topic" and isinstance(kw.value, (ast.Constant, ast.Str)):
                        topic = getattr(kw.value, "value", getattr(kw.value, "s", None))

                calls.append(
                    OutboundCallInfo(
                        caller_service=self.service_name,
                        caller_file=file_path_str,
                        line_no=lineno,
                        call_type="kafka",
                        topic=str(topic) if topic else None,
                    )
                )

        return calls

    def _resolve_target_url(
        self,
        call_args: List[ast.expr],
        env_url_map: dict[str, str],
        keywords: Optional[List[ast.keyword]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve target URL and service hint from call arguments (positional or keyword)."""
        url_expr: Optional[ast.expr] = None
        service_hint: Optional[str] = None

        # 1. Check keyword arguments (e.g. url=..., target_service=...)
        if keywords:
            for kw in keywords:
                if kw.arg == "target_service":
                    val = getattr(kw.value, "value", getattr(kw.value, "s", None))
                    if isinstance(val, str) and not val.isdigit():
                        service_hint = val.strip().lower()
                elif kw.arg in ("url", "uri", "endpoint"):
                    url_expr = kw.value

        # 2. Check positional arguments if not found in keywords
        if url_expr is None and call_args:
            url_expr = call_args[0]
            if len(call_args) > 1 and service_hint is None:
                val = getattr(call_args[1], "value", getattr(call_args[1], "s", None))
                if isinstance(val, str) and not val.isdigit():
                    service_hint = val.strip().lower()

        if url_expr is None:
            return None, service_hint

        # 3. Resolve url_expr (literal string, f-string, or variable)
        # Literal string: "http://orders:8002/orders" or "/orders"
        if isinstance(url_expr, (ast.Constant, ast.Str)):
            val = getattr(url_expr, "value", getattr(url_expr, "s", None))
            if isinstance(val, str):
                if not service_hint and ("http://" in val or "https://" in val):
                    service_hint = self._extract_service_hint_from_url(val)
                return val, service_hint

        # Formatted string: f"{ORDERS_SERVICE_URL}/orders"
        if isinstance(url_expr, ast.JoinedStr):
            parts: List[str] = []
            for part in url_expr.values:
                if isinstance(part, (ast.Constant, ast.Str)):
                    part_val = getattr(part, "value", getattr(part, "s", ""))
                    if isinstance(part_val, str):
                        parts.append(part_val)
                elif isinstance(part, ast.FormattedValue):
                    if isinstance(part.value, ast.Name):
                        var_name = part.value.id
                        if var_name in env_url_map:
                            url_val = env_url_map[var_name]
                            parts.append(url_val)
                            if not service_hint:
                                service_hint = self._extract_service_hint_from_url(url_val)
                        else:
                            parts.append(f"{{{var_name}}}")
                            if not service_hint:
                                clean_hint = var_name.replace("_SERVICE_URL", "").replace("_URL", "").lower()
                                if clean_hint:
                                    service_hint = clean_hint
            full_str = "".join(parts)
            if not service_hint and ("http://" in full_str or "https://" in full_str):
                service_hint = self._extract_service_hint_from_url(full_str)
            return full_str, service_hint

        return None, service_hint

    @staticmethod
    def _extract_service_hint_from_url(url: str) -> Optional[str]:
        """Extract service name from host in URL, e.g. http://orders:8002 -> orders."""
        match = re.search(r"https?://([^/:]+)", url)
        if match:
            host = match.group(1).lower()
            if host not in ("localhost", "127.0.0.1", "0.0.0.0"):
                return host
        return None

    def _chunk_python_file(
        self,
        file_path_str: str,
        full_content: str,
        lines: List[str],
        tree: ast.AST,
        symbols: List[SymbolDefinition],
    ) -> List[CodeChunk]:
        """Segment Python source code into chunks matching function/class boundaries."""
        chunks: List[CodeChunk] = []
        max_chunk_lines = settings.STAGE3_CODE_CHUNK_LINES
        total_lines = len(lines)

        if total_lines == 0:
            return chunks

        # If file is small, make it a single chunk
        if total_lines <= max_chunk_lines:
            chunk_text = full_content
            symbol_names = [s.name for s in symbols]
            chunks.append(
                CodeChunk(
                    chunk_id=f"{self.service_name}:{file_path_str}:1",
                    service_name=self.service_name,
                    file_path=file_path_str,
                    start_line=1,
                    end_line=total_lines,
                    chunk_type=ChunkType.CODE,
                    content=chunk_text,
                    symbol_names=symbol_names,
                    token_estimate=max(1, len(chunk_text) // 4),
                )
            )
            return chunks

        # Group symbols and top-level definitions
        covered_ranges: List[Tuple[int, int, List[str]]] = []
        for sym in symbols:
            # Top-level functions or classes
            if "." not in sym.name:
                covered_ranges.append((sym.start_line, sym.end_line, [sym.name]))

        covered_ranges.sort(key=lambda x: x[0])

        # Add preface / imports chunk if there's code before first symbol
        current_cursor = 1
        for start, end, sym_names in covered_ranges:
            if start > current_cursor:
                preface_text = "\n".join(lines[current_cursor - 1 : start - 1]).strip()
                if preface_text:
                    chunks.append(
                        CodeChunk(
                            chunk_id=f"{self.service_name}:{file_path_str}:{current_cursor}",
                            service_name=self.service_name,
                            file_path=file_path_str,
                            start_line=current_cursor,
                            end_line=start - 1,
                            chunk_type=ChunkType.CODE,
                            content=preface_text,
                            symbol_names=["module_imports"],
                            token_estimate=max(1, len(preface_text) // 4),
                        )
                    )

            # Chunk the symbol definition
            sym_line_count = end - start + 1
            if sym_line_count <= max_chunk_lines:
                sym_text = "\n".join(lines[start - 1 : end])
                chunks.append(
                    CodeChunk(
                        chunk_id=f"{self.service_name}:{file_path_str}:{start}",
                        service_name=self.service_name,
                        file_path=file_path_str,
                        start_line=start,
                        end_line=end,
                        chunk_type=ChunkType.CODE,
                        content=sym_text,
                        symbol_names=sym_names,
                        token_estimate=max(1, len(sym_text) // 4),
                    )
                )
            else:
                # Windowed slicing for very large classes or functions
                step = max_chunk_lines - 10
                for sub_start in range(start, end + 1, step):
                    sub_end = min(end, sub_start + max_chunk_lines - 1)
                    sub_text = "\n".join(lines[sub_start - 1 : sub_end])
                    chunks.append(
                        CodeChunk(
                            chunk_id=f"{self.service_name}:{file_path_str}:{sub_start}",
                            service_name=self.service_name,
                            file_path=file_path_str,
                            start_line=sub_start,
                            end_line=sub_end,
                            chunk_type=ChunkType.CODE,
                            content=sub_text,
                            symbol_names=sym_names,
                            token_estimate=max(1, len(sub_text) // 4),
                        )
                    )

            current_cursor = max(current_cursor, end + 1)

        # Remaining trailing code (e.g., if __name__ == '__main__':)
        if current_cursor <= total_lines:
            trailing_text = "\n".join(lines[current_cursor - 1 : total_lines]).strip()
            if trailing_text:
                chunks.append(
                    CodeChunk(
                        chunk_id=f"{self.service_name}:{file_path_str}:{current_cursor}",
                        service_name=self.service_name,
                        file_path=file_path_str,
                        start_line=current_cursor,
                        end_line=total_lines,
                        chunk_type=ChunkType.CODE,
                        content=trailing_text,
                        symbol_names=["module_main"],
                        token_estimate=max(1, len(trailing_text) // 4),
                    )
                )

        return chunks

    def _chunk_plain_text(
        self,
        file_path_str: str,
        content: str,
        chunk_type: ChunkType,
    ) -> List[CodeChunk]:
        """Split arbitrary non-python files using windowed line blocks."""
        lines = content.splitlines()
        chunks: List[CodeChunk] = []
        step = settings.STAGE3_CODE_CHUNK_LINES
        overlap = 10

        if not lines:
            return chunks

        for start in range(1, len(lines) + 1, max(1, step - overlap)):
            end = min(len(lines), start + step - 1)
            chunk_slice = "\n".join(lines[start - 1 : end]).strip()
            if chunk_slice:
                chunks.append(
                    CodeChunk(
                        chunk_id=f"{self.service_name}:{file_path_str}:{start}",
                        service_name=self.service_name,
                        file_path=file_path_str,
                        start_line=start,
                        end_line=end,
                        chunk_type=chunk_type,
                        content=chunk_slice,
                        symbol_names=[Path(file_path_str).stem],
                        token_estimate=max(1, len(chunk_slice) // 4),
                    )
                )

        return chunks
