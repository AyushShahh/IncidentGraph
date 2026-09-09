"""Pydantic schemas and domain models for the Repository Intelligence & Context Engine."""
from enum import StrEnum
from typing import Any, Optional
from pydantic import BaseModel, Field


class SymbolType(StrEnum):
    """Types of symbols extracted from source code AST."""
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    CLASS = "class"
    METHOD = "method"
    ROUTE = "route"
    CONSTANT = "constant"


class RouteInfo(BaseModel):
    """Metadata describing an HTTP endpoint exposed by a service."""
    method: str
    path: str
    summary: Optional[str] = None
    response_model: Optional[str] = None


class SymbolDefinition(BaseModel):
    """Extracted code symbol with location, signature, and metadata."""
    name: str
    symbol_type: SymbolType
    service_name: str
    file_path: str
    start_line: int
    end_line: int
    signature: Optional[str] = None
    docstring: Optional[str] = None
    route_info: Optional[RouteInfo] = None


class ChunkType(StrEnum):
    """Categorization of an indexed code/doc chunk."""
    CODE = "code"
    DOC = "documentation"
    CONFIG = "configuration"


class CodeChunk(BaseModel):
    """A granular slice of code, markdown, or config for retrieval and vector embedding."""
    chunk_id: str
    service_name: str
    file_path: str
    start_line: int
    end_line: int
    chunk_type: ChunkType = ChunkType.CODE
    content: str
    symbol_names: list[str] = Field(default_factory=list)
    token_estimate: int = 0


class DependencyEdgeType(StrEnum):
    """Type of interaction between services."""
    HTTP = "http"
    ASYNC_EVENT = "async_event"
    STORAGE = "storage"


class DependencyEdge(BaseModel):
    """Directed dependency link between two services."""
    source_service: str
    target_service: str
    edge_type: DependencyEdgeType = DependencyEdgeType.HTTP
    protocol: str = "http"
    endpoint: Optional[str] = None
    method: Optional[str] = None
    topic: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class DependencyNode(BaseModel):
    """Topological representation of a service node in the system graph."""
    service_name: str
    exposed_routes: list[RouteInfo] = Field(default_factory=list)
    downstream_dependencies: list[str] = Field(default_factory=list)
    upstream_callers: list[str] = Field(default_factory=list)
    in_degree_centrality: float = 0.0
    out_degree_centrality: float = 0.0


class BlastRadiusResult(BaseModel):
    """Blast radius assessment for a target service failure."""
    target_service: str
    impact_level: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    direct_callers: list[str] = Field(default_factory=list)
    transitive_callers: list[str] = Field(default_factory=list)
    downstream_dependencies: list[str] = Field(default_factory=list)
    affected_routes: list[str] = Field(default_factory=list)
    summary: str = ""


class FileManifest(BaseModel):
    """Fingerprint and metadata for an individual file in a repository."""
    file_path: str
    sha256_hash: str
    last_modified: float
    file_size_bytes: int
    chunk_count: int
    symbol_count: int


class RepositoryManifest(BaseModel):
    """Complete manifest tracking index state and checksums for a service repository."""
    service_name: str
    root_path: str
    last_indexed_at: str
    file_count: int
    total_chunks: int
    total_symbols: int
    files: dict[str, FileManifest] = Field(default_factory=dict)


class CodeSnippet(BaseModel):
    """A contextual code excerpt included in an agent context package."""
    service_name: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    reason: str = ""


class ContextPackage(BaseModel):
    """Token-bounded deterministic context package assembled for the Stage 4 agent."""
    incident_id: Optional[str] = None
    primary_service: str
    target_files: list[str] = Field(default_factory=list)
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    symbols: list[SymbolDefinition] = Field(default_factory=list)
    dependency_summary: dict[str, Any] = Field(default_factory=dict)
    blast_radius: Optional[BlastRadiusResult] = None
    estimated_tokens: int = 0
    token_budget: int = 3500
    truncated: bool = False
