"""Coordinator orchestrating repository discovery, incremental diffing, parsing, and indexing.

Coordinates AST parsing, symbol indexing, dependency graph construction, and vector upsert.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging import get_logger
from backend.repository.dependency_graph import DependencyGraph, get_dependency_graph
from backend.repository.discovery import RepositoryDiscovery
from backend.repository.manifest import ManifestManager
from backend.repository.parser import CodeParser, OutboundCallInfo
from backend.repository.schemas import (
    ChunkType,
    CodeChunk,
    FileManifest,
    RepositoryManifest,
    SymbolDefinition,
)
from backend.repository.symbol_index import SymbolIndex, get_symbol_index
from backend.repository.vector_indexer import VectorIndexer

logger = get_logger(__name__)


class RepositoryIndexer:
    """Master orchestrator for multi-repository indexing and knowledge maintenance."""

    def __init__(
        self,
        discovery: Optional[RepositoryDiscovery] = None,
        manifest_mgr: Optional[ManifestManager] = None,
        symbol_index: Optional[SymbolIndex] = None,
        dependency_graph: Optional[DependencyGraph] = None,
        vector_indexer: Optional[VectorIndexer] = None,
    ) -> None:
        self.discovery = discovery or RepositoryDiscovery()
        self.manifest_mgr = manifest_mgr or ManifestManager()
        self.symbol_index = symbol_index or get_symbol_index()
        self.dependency_graph = dependency_graph or get_dependency_graph()
        self.vector_indexer = vector_indexer or VectorIndexer()

        # Cache of discovered service paths: service_name -> Path
        self._service_paths: Dict[str, Path] = {}
        # Outbound calls per service: service_name -> list[OutboundCallInfo]
        self._outbound_calls: Dict[str, List[OutboundCallInfo]] = {}
        # In-memory code chunks cache: (service_name, rel_path) -> list[CodeChunk]
        self._chunks_cache: Dict[tuple[str, str], List[CodeChunk]] = {}
        # Manifests cache: service_name -> RepositoryManifest
        self._manifests: Dict[str, RepositoryManifest] = {}
        self._is_indexing: bool = False
        self._last_index_time: Optional[str] = None

    def get_service_path(self, service_name: str) -> Optional[Path]:
        """Retrieve the filesystem path for a discovered service."""
        return self._service_paths.get(service_name.lower())

    def list_services(self) -> List[str]:
        """List all discovered service names."""
        return sorted(list(self._service_paths.keys()))

    def get_manifest(self, service_name: str) -> Optional[RepositoryManifest]:
        """Retrieve the current manifest for a service."""
        svc = service_name.lower()
        if svc in self._manifests:
            return self._manifests[svc]
        manifest = self.manifest_mgr.load_manifest(svc)
        if manifest:
            self._manifests[svc] = manifest
        return manifest

    async def index_all_repositories(self, force: bool = False) -> Dict[str, Any]:
        """Discover and index all services in configured repository roots."""
        if self._is_indexing:
            return {"status": "already_indexing", "message": "An indexing run is already in progress."}

        self._is_indexing = True
        start_time = datetime.now(timezone.utc)
        results: Dict[str, Any] = {}

        try:
            # 1. Discover all service directories
            self._service_paths = self.discovery.discover()
            logger.info("Starting indexing for %d services: %s", len(self._service_paths), list(self._service_paths.keys()))

            for svc_name, svc_path in self._service_paths.items():
                res = await self._index_single_service(svc_name, svc_path, force=force)
                results[svc_name] = res

            # 2. Rebuild the system-wide static dependency graph
            all_calls: List[OutboundCallInfo] = []
            for calls in self._outbound_calls.values():
                all_calls.extend(calls)

            all_routes = self.symbol_index.get_all_routes()
            self.dependency_graph.build_from_parsed_data(
                service_names=list(self._service_paths.keys()),
                service_routes=all_routes,
                outbound_calls=all_calls,
            )

            self._last_index_time = datetime.now(timezone.utc).isoformat()
            duration_s = (datetime.now(timezone.utc) - start_time).total_seconds()

            return {
                "status": "completed",
                "indexed_services": list(self._service_paths.keys()),
                "duration_seconds": round(duration_s, 2),
                "total_symbols": self.symbol_index.total_symbols,
                "service_results": results,
            }

        finally:
            self._is_indexing = False

    async def index_repository(self, service_name: str, force: bool = False) -> Dict[str, Any]:
        """Index or reindex a single service repository."""
        svc = service_name.lower()
        if not self._service_paths:
            self._service_paths = self.discovery.discover()

        if svc not in self._service_paths:
            return {"status": "not_found", "message": f"Service '{service_name}' not found."}

        svc_path = self._service_paths[svc]
        res = await self._index_single_service(svc, svc_path, force=force)

        # Re-sync dependency graph
        all_calls: List[OutboundCallInfo] = []
        for calls in self._outbound_calls.values():
            all_calls.extend(calls)

        self.dependency_graph.build_from_parsed_data(
            service_names=list(self._service_paths.keys()),
            service_routes=self.symbol_index.get_all_routes(),
            outbound_calls=all_calls,
        )

        return {"status": "completed", "service": svc, "details": res}

    async def ensure_initialized(self) -> None:
        """Ensure all repositories are discovered and indexed in memory."""
        if not self._service_paths or self.symbol_index.total_symbols == 0:
            await self.index_all_repositories(force=False)

    async def _index_single_service(
        self,
        service_name: str,
        service_root: Path,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Perform indexing on an individual service repository.

        Always parses code files to maintain complete in-memory symbols, routes,
        and outbound calls. Only generates and upserts vector embeddings for
        added or modified files, ensuring 100% incremental vector operations.
        """
        current_files = self.discovery.scan_repository_files(service_root)
        parser = CodeParser(service_name=service_name)

        diff, existing_manifest = self.manifest_mgr.diff_repository(
            service_name, service_root, current_files
        )

        files_to_embed = set(diff.added + diff.modified) if not force else set(current_files)
        deleted_files = diff.deleted

        # Handle deleted files
        for del_path in deleted_files:
            self.symbol_index.remove_file_symbols(service_name, del_path)
            await self.vector_indexer.delete_file_chunks(service_name, del_path)
            self._chunks_cache.pop((service_name, del_path), None)

        # Clear existing in-memory symbols for this service before re-populating
        self.symbol_index.remove_service_symbols(service_name)

        new_chunks_to_embed: List[CodeChunk] = []
        service_outbound: List[OutboundCallInfo] = []
        file_manifests: Dict[str, FileManifest] = {}

        for file_path in current_files:
            rel_path = self.discovery.get_relative_path(file_path, service_root)
            needs_embed = file_path in files_to_embed

            # If modified and needs embed, purge old vectors first
            if needs_embed and not force and file_path in diff.modified:
                await self.vector_indexer.delete_file_chunks(service_name, rel_path)

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.error("Failed to read %s: %s", file_path, exc)
                continue

            symbols: List[SymbolDefinition] = []
            chunks: List[CodeChunk] = []

            ext = file_path.suffix.lower()
            if ext == ".py":
                symbols, outbound, chunks = parser.parse_python_file(rel_path, content)
                service_outbound.extend(outbound)
            elif ext == ".md":
                chunks = parser.parse_markdown_file(rel_path, content)
            else:
                chunks = parser.parse_config_file(rel_path, content)

            # In-memory symbol table and chunk cache are always populated
            self.symbol_index.add_symbols(symbols)
            self._chunks_cache[(service_name, rel_path)] = chunks

            # Only embed in Qdrant if file is new or modified
            if needs_embed:
                new_chunks_to_embed.extend(chunks)

            file_manifests[rel_path] = self.manifest_mgr.build_file_manifest(
                file_path=file_path,
                service_root=service_root,
                chunk_count=len(chunks),
                symbol_count=len(symbols),
            )

        # Upsert new and modified chunks to Qdrant
        if new_chunks_to_embed:
            await self.vector_indexer.upsert_chunks(new_chunks_to_embed)

        self._outbound_calls[service_name] = service_outbound

        # Build and persist repository manifest
        svc_symbols = len(
            self.symbol_index.search_symbols("", service=service_name, limit=10000)
        )
        repo_manifest = self.manifest_mgr.create_repository_manifest(
            service_name=service_name,
            service_root=service_root,
            file_manifests=file_manifests,
            total_symbols=svc_symbols,
        )
        self.manifest_mgr.save_manifest(repo_manifest)
        self._manifests[service_name] = repo_manifest

        return {
            "action": "indexed" if files_to_embed else "reloaded_memory",
            "added_count": len(diff.added) if not force else len(current_files),
            "modified_count": len(diff.modified) if not force else 0,
            "deleted_count": len(deleted_files),
            "embedded_chunks": len(new_chunks_to_embed),
            "total_files": len(file_manifests),
            "total_chunks": repo_manifest.total_chunks,
            "total_symbols": svc_symbols,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get indexer operational status and health metrics."""
        return {
            "is_indexing": self._is_indexing,
            "last_index_time": self._last_index_time,
            "discovered_services": list(self._service_paths.keys()),
            "total_services": len(self._service_paths),
            "total_symbols": self.symbol_index.total_symbols,
            "dependency_nodes": len(self.dependency_graph.get_full_topology()["nodes"]),
            "dependency_edges": len(self.dependency_graph.get_full_topology()["edges"]),
        }


# Global singleton indexer
_repository_indexer = RepositoryIndexer()


def get_repository_indexer() -> RepositoryIndexer:
    """Obtain singleton indexer instance."""
    return _repository_indexer
