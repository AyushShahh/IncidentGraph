"""Deterministic retrieval tools for the Incident Investigation Agent.

Provides 14 high-efficiency tools for code search, file inspection, symbol resolution,
dependency analysis, and blast radius calculation.
NO LLM logic or heuristics.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging import get_logger
from backend.repository.dependency_graph import get_dependency_graph
from backend.repository.indexer import get_repository_indexer
from backend.repository.schemas import (
    BlastRadiusResult,
    ChunkType,
    CodeChunk,
    RepositoryManifest,
    RouteInfo,
    SymbolDefinition,
)
from backend.repository.symbol_index import get_symbol_index
from backend.repository.vector_indexer import VectorIndexer

logger = get_logger(__name__)


class RepositoryTools:
    """Deterministic toolset for repository exploration and context retrieval."""

    def __init__(self) -> None:
        self.indexer = get_repository_indexer()
        self.symbol_index = get_symbol_index()
        self.graph = get_dependency_graph()
        self.vector_indexer = VectorIndexer()

    def _resolve_file(self, service: str, file_path: str) -> Optional[Path]:
        """Resolve a relative file path within a service directory."""
        svc_path = self.indexer.get_service_path(service)
        if not svc_path:
            # Try finding service root dynamically
            services = self.indexer.discovery.discover()
            if service.lower() in services:
                svc_path = services[service.lower()]
            else:
                return None

        target = (svc_path / file_path).resolve()
        # Ensure path stays within service root
        try:
            target.relative_to(svc_path.resolve())
        except ValueError:
            return None

        return target if target.exists() and target.is_file() else None

    # -------------------------------------------------------------------------
    # Tool 1: search_code
    # -------------------------------------------------------------------------
    async def search_code(
        self,
        query: str,
        service: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Semantically search code, markdown docs, and config across repositories."""
        hits = await self.vector_indexer.search_code(
            query=query,
            service=service,
            limit=limit,
        )

        results: List[Dict[str, Any]] = []
        for chunk, score in hits:
            results.append(
                {
                    "service": chunk.service_name,
                    "file_path": chunk.file_path,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "chunk_type": chunk.chunk_type.value,
                    "content": chunk.content,
                    "symbols": chunk.symbol_names,
                    "similarity_score": round(score, 3),
                }
            )

        # Lexical fallback if vector search yielded zero hits (e.g. mock / test env)
        if not results:
            svc_filter = service.lower() if service else None
            matched = []
            for (svc_name, rel_path), chunks in self.indexer._chunks_cache.items():
                if svc_filter and svc_name.lower() != svc_filter:
                    continue
                for c in chunks:
                    if query.lower() in c.content.lower():
                        prio = 0 if c.chunk_type == ChunkType.CODE else (1 if c.chunk_type == ChunkType.CONFIG else 2)
                        matched.append((prio, {
                            "service": c.service_name,
                            "file_path": c.file_path,
                            "start_line": c.start_line,
                            "end_line": c.end_line,
                            "chunk_type": c.chunk_type.value,
                            "content": c.content,
                            "symbols": c.symbol_names,
                            "similarity_score": 1.0,
                        }))
            matched.sort(key=lambda x: x[0])
            results = [m[1] for m in matched[:limit]]

        return results

    # -------------------------------------------------------------------------
    # Tool 2: read_file
    # -------------------------------------------------------------------------
    def read_file(
        self,
        service: str,
        file_path: str,
        max_lines: int = 300,
    ) -> Dict[str, Any]:
        """Read file content with line count limiting."""
        target = self._resolve_file(service, file_path)
        if not target:
            return {"error": f"File '{file_path}' not found in service '{service}'."}

        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)
            truncated = total_lines > max_lines
            content_lines = lines[:max_lines]

            numbered = [f"{i + 1:4d}: {line}" for i, line in enumerate(content_lines)]

            return {
                "service": service,
                "file_path": file_path,
                "total_lines": total_lines,
                "lines_returned": len(content_lines),
                "truncated": truncated,
                "content": "\n".join(numbered),
            }
        except Exception as exc:
            return {"error": f"Failed reading file: {exc}"}

    # -------------------------------------------------------------------------
    # Tool 3: read_lines
    # -------------------------------------------------------------------------
    def read_lines(
        self,
        service: str,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> Dict[str, Any]:
        """Read a specific 1-indexed line range from a file."""
        target = self._resolve_file(service, file_path)
        if not target:
            return {"error": f"File '{file_path}' not found in service '{service}'."}

        if start_line < 1:
            start_line = 1
        if end_line < start_line:
            end_line = start_line

        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)
            slice_end = min(total_lines, end_line)
            slice_lines = lines[start_line - 1 : slice_end]

            numbered = [f"{start_line + i:4d}: {l}" for i, l in enumerate(slice_lines)]

            return {
                "service": service,
                "file_path": file_path,
                "start_line": start_line,
                "end_line": slice_end,
                "total_lines": total_lines,
                "content": "\n".join(numbered),
            }
        except Exception as exc:
            return {"error": f"Failed reading line range: {exc}"}

    # -------------------------------------------------------------------------
    # Tool 4: find_symbol
    # -------------------------------------------------------------------------
    def find_symbol(
        self,
        symbol_name: str,
        service: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Look up symbol definitions by exact or qualified name."""
        matches = self.symbol_index.find_symbol(symbol_name, service=service)
        return [m.model_dump() for m in matches]

    # -------------------------------------------------------------------------
    # Tool 5: find_referencing_files
    # -------------------------------------------------------------------------
    def find_referencing_files(
        self,
        symbol_name: str,
        service: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find source files that reference or call a given symbol."""
        results: List[Dict[str, Any]] = []
        svc_path_map = self.indexer._service_paths
        if not svc_path_map:
            svc_path_map = self.indexer.discovery.discover()

        target_services = [service.lower()] if service else list(svc_path_map.keys())

        for svc in target_services:
            root = svc_path_map.get(svc)
            if not root:
                continue

            files = self.indexer.discovery.scan_repository_files(root)
            for f in files:
                rel = self.indexer.discovery.get_relative_path(f, root)
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    if symbol_name in text:
                        # Count occurrences
                        count = text.count(symbol_name)
                        results.append(
                            {
                                "service": svc,
                                "file_path": rel,
                                "occurrence_count": count,
                            }
                        )
                except Exception:
                    continue

        return results

    # -------------------------------------------------------------------------
    # Tool 6: list_directory
    # -------------------------------------------------------------------------
    def list_directory(
        self,
        service: str,
        relative_path: str = "",
    ) -> Dict[str, Any]:
        """List files and directories within a service repository."""
        svc_path = self.indexer.get_service_path(service)
        if not svc_path:
            return {"error": f"Service '{service}' not found."}

        target_dir = (svc_path / relative_path).resolve()
        try:
            target_dir.relative_to(svc_path.resolve())
        except ValueError:
            return {"error": "Invalid relative path traversal."}

        if not target_dir.exists() or not target_dir.is_dir():
            return {"error": f"Directory '{relative_path}' not found in service '{service}'."}

        entries = []
        for item in sorted(target_dir.iterdir()):
            if item.name.startswith("."):
                continue
            entries.append(
                {
                    "name": item.name,
                    "is_directory": item.is_dir(),
                    "size_bytes": item.stat().st_size if item.is_file() else None,
                }
            )

        return {
            "service": service,
            "path": relative_path or ".",
            "entries": entries,
        }

    # -------------------------------------------------------------------------
    # Tool 7: lookup_dependencies
    # -------------------------------------------------------------------------
    def lookup_dependencies(self, service: str) -> Dict[str, Any]:
        """Get downstream dependencies and upstream callers for a service."""
        downstream = self.graph.get_dependencies(service)
        upstream = self.graph.get_dependents(service)

        return {
            "service": service,
            "downstream_dependencies": downstream,
            "upstream_callers": upstream,
        }

    def find_callers(self, service: str) -> List[str]:
        """Get services that directly call this service (upstream callers)."""
        return self.graph.get_dependents(service)

    def find_dependencies(self, service: str) -> List[str]:
        """Get services that this service directly calls (downstream dependencies)."""
        return self.graph.get_dependencies(service)

    # -------------------------------------------------------------------------
    # Tool 8: get_blast_radius
    # -------------------------------------------------------------------------
    def get_blast_radius(self, service: str) -> Dict[str, Any]:
        """Calculate system-wide blast radius if the target service fails."""
        res: BlastRadiusResult = self.graph.get_blast_radius(service)
        return res.model_dump()

    # -------------------------------------------------------------------------
    # Tool 9: get_service_routes
    # -------------------------------------------------------------------------
    def get_service_routes(self, service: str) -> List[Dict[str, Any]]:
        """Get all HTTP endpoints registered for a service."""
        routes = self.symbol_index.get_service_routes(service)
        if not routes and hasattr(self, "graph") and self.graph:
            routes = self.graph.get_service_routes(service) if hasattr(self.graph, "get_service_routes") else self.graph._service_routes.get(service.lower(), [])
        return [r.model_dump() for r in routes]

    # -------------------------------------------------------------------------
    # Tool 10: get_service_manifest
    # -------------------------------------------------------------------------
    def get_service_manifest(self, service: str) -> Dict[str, Any]:
        """Get indexing manifest and file checksums for a service."""
        manifest = self.indexer.get_manifest(service)
        if not manifest:
            return {"error": f"No manifest found for service '{service}'."}
        return manifest.model_dump()

    # -------------------------------------------------------------------------
    # Tool 11: list_indexed_services
    # -------------------------------------------------------------------------
    def list_indexed_services(self) -> List[str]:
        """List all discovered and indexable microservices."""
        services = self.indexer.list_services()
        if not services:
            # Trigger quick discovery if indexer hasn't run yet
            services = sorted(list(self.indexer.discovery.discover().keys()))
        return services

    # -------------------------------------------------------------------------
    # Tool 12: get_topology_graph
    # -------------------------------------------------------------------------
    def get_topology_graph(self) -> Dict[str, Any]:
        """Export the complete system dependency graph."""
        return self.graph.get_full_topology()

    # -------------------------------------------------------------------------
    # Tool 13: read_config
    # -------------------------------------------------------------------------
    def read_config(self, service: str, config_name: str) -> Dict[str, Any]:
        """Read service configuration or manifest files (Dockerfile, requirements, etc.)."""
        valid_configs = {
            "dockerfile",
            "requirements.txt",
            "pyproject.toml",
            "readme.md",
            "config.py",
            "settings.py",
        }
        clean_name = config_name.strip().lower()
        target = self._resolve_file(service, config_name)

        if not target:
            # Search case-insensitively in service root
            svc_path = self.indexer.get_service_path(service)
            if svc_path:
                for item in svc_path.iterdir():
                    if item.is_file() and item.name.lower() == clean_name:
                        target = item
                        break

        if not target:
            return {"error": f"Config file '{config_name}' not found in '{service}'."}

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            return {
                "service": service,
                "config_name": target.name,
                "content": content,
            }
        except Exception as exc:
            return {"error": f"Failed reading config: {exc}"}

    # -------------------------------------------------------------------------
    # Tool 14: build_incident_context
    # -------------------------------------------------------------------------
    async def build_incident_context(
        self,
        incident_id: Optional[str],
        service: str,
        error_trace: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        token_budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Synthesize a token-bounded context package for an incident."""
        from backend.repository.context_builder import ContextBuilder

        builder = ContextBuilder(self)
        pkg = await builder.build_context(
            incident_id=incident_id,
            service=service,
            error_trace=error_trace,
            file_paths=file_paths,
            token_budget=token_budget,
        )
        return pkg.model_dump()


# Global tools singleton
_repository_tools = RepositoryTools()


def get_repository_tools() -> RepositoryTools:
    """Obtain singleton tools instance."""
    return _repository_tools
