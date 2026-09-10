"""REST API endpoints for repository intelligence, dependency topology, and context packaging."""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.repository.dependency_graph import get_dependency_graph
from backend.repository.indexer import get_repository_indexer
from backend.repository.schemas import BlastRadiusResult, ContextPackage, SymbolType
from backend.repository.symbol_index import get_symbol_index
from backend.repository.tools import get_repository_tools

router = APIRouter()


class BuildContextRequest(BaseModel):
    """Payload for on-demand context package synthesis."""
    service: Optional[str] = None
    primary_service: Optional[str] = None
    incident_id: Optional[str] = None
    error_trace: Optional[str] = None
    error_message: Optional[str] = None
    file_paths: Optional[List[str]] = Field(default=None)
    token_budget: Optional[int] = None
    max_tokens: Optional[int] = None

    def get_service(self) -> str:
        svc = self.service or self.primary_service
        if not svc:
            raise ValueError("Field 'service' or 'primary_service' is required.")
        return svc

    def get_error_trace(self) -> Optional[str]:
        return self.error_trace or self.error_message

    def get_token_budget(self) -> Optional[int]:
        return self.token_budget or self.max_tokens


@router.get("", summary="List all discovered and indexed service repositories")
async def list_repositories() -> Dict[str, Any]:
    """Retrieve catalog of discovered service repositories with indexing summaries."""
    indexer = get_repository_indexer()
    services = indexer.list_services()

    # If not yet indexed, discover available services
    if not services:
        services = sorted(list(indexer.discovery.discover().keys()))

    summaries = []
    for svc in services:
        manifest = indexer.get_manifest(svc)
        summaries.append(
            {
                "service": svc,
                "path": str(indexer.get_service_path(svc) or ""),
                "indexed": manifest is not None,
                "file_count": manifest.file_count if manifest else 0,
                "total_chunks": manifest.total_chunks if manifest else 0,
                "total_symbols": manifest.total_symbols if manifest else 0,
                "last_indexed_at": manifest.last_indexed_at if manifest else None,
            }
        )

    return {
        "total_repositories": len(summaries),
        "repositories": summaries,
    }


@router.get("/status", summary="Get repository indexer status and metrics")
async def get_indexer_status() -> Dict[str, Any]:
    """Get operational status and stats of the repository intelligence engine."""
    indexer = get_repository_indexer()
    return indexer.get_status()


@router.post("/reindex", summary="Trigger reindexing of all service repositories")
async def reindex_all(force: bool = Query(default=False)) -> Dict[str, Any]:
    """Initiate multi-repository incremental indexing."""
    indexer = get_repository_indexer()
    result = await indexer.index_all_repositories(force=force)
    return result


@router.post("/reindex/{service}", summary="Trigger reindexing of an individual service repository")
async def reindex_service(service: str, force: bool = Query(default=False)) -> Dict[str, Any]:
    """Initiate indexing for a specific named service repository."""
    indexer = get_repository_indexer()
    result = await indexer.index_repository(service, force=force)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.get("/dependency-graph", summary="Get complete system dependency topology")
async def get_dependency_topology() -> Dict[str, Any]:
    """Return the entire directed dependency graph with nodes, edges, and centralities."""
    indexer = get_repository_indexer()
    await indexer.ensure_initialized()
    graph = get_dependency_graph()
    return graph.get_full_topology()


@router.get("/blast-radius/{service}", summary="Calculate blast radius for a service failure", response_model=BlastRadiusResult)
async def get_blast_radius(service: str) -> BlastRadiusResult:
    """Assess upstream callers and system blast radius if the specified service fails."""
    indexer = get_repository_indexer()
    await indexer.ensure_initialized()
    graph = get_dependency_graph()
    return graph.get_blast_radius(service)


@router.get("/symbols/search", summary="Search indexed symbols across repositories")
async def search_symbols(
    query: str = Query(default=""),
    service: Optional[str] = Query(default=None),
    symbol_type: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """Search code symbols (functions, classes, routes, methods) by name with filters."""
    indexer = get_repository_indexer()
    await indexer.ensure_initialized()
    symbol_index = get_symbol_index()
    type_enum = None
    if symbol_type:
        try:
            type_enum = SymbolType(symbol_type.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid symbol_type '{symbol_type}'. Allowed: {[t.value for t in SymbolType]}",
            )

    matches = symbol_index.search_symbols(
        query=query,
        service=service,
        symbol_type=type_enum,
        limit=limit,
    )
    return [m.model_dump() for m in matches]


context_router = APIRouter()


@context_router.post("/build", summary="Synthesize a token-bounded context package", response_model=ContextPackage)
@router.post("/context/build", summary="Synthesize a token-bounded context package (alias)", response_model=ContextPackage)
async def build_context_package(payload: BuildContextRequest) -> ContextPackage:
    """Assemble deterministic, token-budgeted incident context for agent consumption."""
    service_name = payload.service or payload.primary_service
    error_trace = payload.get_error_trace()

    # If service or trace is missing, hydrate from PostgreSQL via incident_id
    if payload.incident_id and (not service_name or not error_trace):
        from sqlalchemy import select
        import uuid
        from backend.db.session import async_session_factory
        from backend.models.incident import Incident

        try:
            inc_uuid = uuid.UUID(payload.incident_id)
            async with async_session_factory() as session:
                stmt = select(Incident).where(Incident.id == inc_uuid)
                res = await session.execute(stmt)
                inc = res.scalar_one_or_none()
                if inc:
                    if not service_name:
                        service_name = inc.primary_service
                    if not error_trace and inc.representative_log:
                        error_trace = (
                            inc.representative_log.get("traceback")
                            or inc.representative_log.get("stack_trace")
                            or inc.representative_log.get("message")
                        )
                    if not error_trace and inc.candidates:
                        first_cand = inc.candidates[0]
                        if first_cand.representative_log:
                            error_trace = (
                                first_cand.representative_log.get("traceback")
                                or first_cand.representative_log.get("stack_trace")
                            )
                        if not error_trace:
                            error_trace = first_cand.normalized_text
        except Exception:
            pass

    if not service_name:
        raise HTTPException(
            status_code=422,
            detail="Could not resolve 'service'. Please provide 'service' or a valid 'incident_id'.",
        )

    tools = get_repository_tools()
    pkg_dict = await tools.build_incident_context(
        incident_id=payload.incident_id,
        service=service_name,
        error_trace=error_trace,
        file_paths=payload.file_paths,
        token_budget=payload.get_token_budget(),
    )
    return ContextPackage.model_validate(pkg_dict)


@router.get("/search", summary="Semantically search code chunks across repositories")
async def search_code(
    query: str = Query(..., description="Natural language or code query to search for"),
    service: Optional[str] = Query(default=None, description="Optional service name filter"),
    limit: int = Query(default=5, ge=1, le=50, description="Max number of chunks to return"),
) -> List[Dict[str, Any]]:
    """Search code snippets, markdown docs, and configs via vector or lexical search."""
    indexer = get_repository_indexer()
    await indexer.ensure_initialized()
    tools = get_repository_tools()
    return await tools.search_code(query=query, service=service, limit=limit)


@router.get("/files/content", summary="Read file content or line range from a service")
async def get_file_content(
    service: str = Query(..., description="Service name owning the file"),
    path: str = Query(..., description="Relative path within the service"),
    start_line: Optional[int] = Query(default=None, ge=1, description="Optional 1-indexed start line"),
    end_line: Optional[int] = Query(default=None, ge=1, description="Optional 1-indexed end line"),
    max_lines: int = Query(default=300, ge=1, le=1000, description="Max lines to return if range omitted"),
) -> Dict[str, Any]:
    """Retrieve line-numbered file contents or a slice from a service repository."""
    indexer = get_repository_indexer()
    await indexer.ensure_initialized()
    tools = get_repository_tools()
    if start_line is not None:
        end = end_line if end_line is not None else (start_line + max_lines)
        res = tools.read_lines(service=service, file_path=path, start_line=start_line, end_line=end)
    else:
        res = tools.read_file(service=service, file_path=path, max_lines=max_lines)

    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.get("/routes/{service}", summary="Get all exposed HTTP routes for a service")
async def get_service_routes(service: str) -> List[Dict[str, Any]]:
    """Return all routes registered for the given service."""
    indexer = get_repository_indexer()
    await indexer.ensure_initialized()
    tools = get_repository_tools()
    return tools.get_service_routes(service=service)

