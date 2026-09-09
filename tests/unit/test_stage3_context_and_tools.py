"""Unit tests for Stage 3 retrieval tools and token-bounded context builder."""
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch

from backend.repository.context_builder import ContextBuilder
from backend.repository.dependency_graph import DependencyGraph
from backend.repository.discovery import RepositoryDiscovery
from backend.repository.indexer import RepositoryIndexer
from backend.repository.manifest import ManifestManager
from backend.repository.schemas import (
    BlastRadiusResult,
    CodeChunk,
    RouteInfo,
    SymbolDefinition,
    SymbolType,
)
from backend.repository.symbol_index import SymbolIndex
from backend.repository.tools import RepositoryTools


@pytest.fixture
def mock_environment(tmp_path: Path):
    """Set up an isolated multi-service repository test environment."""
    services_root = tmp_path / "services"
    services_root.mkdir()

    # Create service 'orders'
    orders_dir = services_root / "orders"
    orders_dir.mkdir()
    (orders_dir / "main.py").write_text(
        "\"\"\"Orders service.\"\"\"\n"
        "def create_order(user_id: str):\n"
        "    print('Creating order')\n"
        "    raise KeyError('missing customer tier')\n"
        "def health(): return 'ok'\n",
        encoding="utf-8",
    )
    (orders_dir / "Dockerfile").write_text("FROM python:3.11\nCMD ['python', 'main.py']\n", encoding="utf-8")

    # Set up indexer & discovery
    discovery = RepositoryDiscovery(root_dirs=[str(services_root)])
    manifest_mgr = ManifestManager(storage_dir=str(tmp_path / "manifests"))
    symbol_index = SymbolIndex()
    dep_graph = DependencyGraph()

    # Pre-populate symbol index and graph
    symbol_index.add_symbols([
        SymbolDefinition(
            name="create_order",
            symbol_type=SymbolType.FUNCTION,
            service_name="orders",
            file_path="main.py",
            start_line=2,
            end_line=4,
            signature="def create_order(user_id: str):",
            docstring="Create new order.",
        ),
        SymbolDefinition(
            name="post_orders",
            symbol_type=SymbolType.ROUTE,
            service_name="orders",
            file_path="main.py",
            start_line=1,
            end_line=5,
            route_info=RouteInfo(method="POST", path="/orders"),
        ),
    ])
    dep_graph.add_service_node("orders", [RouteInfo(method="POST", path="/orders")])
    dep_graph.add_service_node("gateway", [RouteInfo(method="POST", path="/api/checkout")])

    indexer = RepositoryIndexer(
        discovery=discovery,
        manifest_mgr=manifest_mgr,
        symbol_index=symbol_index,
        dependency_graph=dep_graph,
    )
    indexer._service_paths["orders"] = orders_dir

    tools = RepositoryTools()
    tools.indexer = indexer
    tools.symbol_index = symbol_index
    tools.graph = dep_graph

    return tools, orders_dir


def test_tools_file_reading(mock_environment):
    """Verify read_file and read_lines tools."""
    tools, orders_dir = mock_environment

    # 1. read_file
    res_file = tools.read_file(service="orders", file_path="main.py", max_lines=10)
    assert res_file.get("service") == "orders"
    assert res_file.get("total_lines") == 5
    assert "create_order" in res_file.get("content", "")

    # 2. read_lines
    res_lines = tools.read_lines(service="orders", file_path="main.py", start_line=2, end_line=4)
    assert res_lines.get("start_line") == 2
    assert res_lines.get("end_line") == 4
    assert "KeyError" in res_lines.get("content", "")

    # 3. read_config
    res_cfg = tools.read_config(service="orders", config_name="Dockerfile")
    assert "FROM python:3.11" in res_cfg.get("content", "")


def test_tools_symbol_and_search(mock_environment):
    """Verify find_symbol and find_referencing_files."""
    tools, _ = mock_environment

    syms = tools.find_symbol("create_order", service="orders")
    assert len(syms) == 1
    assert syms[0]["name"] == "create_order"

    refs = tools.find_referencing_files("create_order", service="orders")
    assert len(refs) == 1
    assert refs[0]["file_path"] == "main.py"


@pytest.mark.asyncio
async def test_tools_dependency_and_routes(mock_environment):
    """Verify get_service_routes, find_callers, find_dependencies, and blast_radius tools."""
    tools, _ = mock_environment
    tools.graph.add_dependency_edge(caller="gateway", callee="orders", endpoint="/orders")

    # 1. Routes
    routes = tools.get_service_routes("orders")
    assert len(routes) == 1
    assert routes[0]["path"] == "/orders"

    # 2. Callers & Dependencies
    callers = tools.find_callers("orders")
    assert "gateway" in callers

    deps = tools.find_dependencies("gateway")
    assert "orders" in deps

    # 3. Blast radius
    radius = tools.get_blast_radius("orders")
    target_svc = radius["target_service"] if isinstance(radius, dict) else radius.target_service
    callers_list = radius["direct_callers"] if isinstance(radius, dict) else radius.direct_callers
    assert target_svc == "orders"
    assert "gateway" in callers_list

    # 4. Topology & Indexed services
    services = tools.list_indexed_services()
    assert "orders" in services

    topo = tools.get_topology_graph()
    assert topo["total_nodes"] >= 2
    assert topo["total_edges"] >= 1


@pytest.mark.asyncio
async def test_context_builder_trace_parsing_and_token_budgeting(mock_environment):
    """Verify traceback parsing, error snippet inclusion, and token bounding in ContextBuilder."""
    tools, _ = mock_environment
    builder = ContextBuilder(tools_instance=tools)

    traceback_sample = (
        'Traceback (most recent call last):\n'
        '  File "/app/services/orders/main.py", line 4, in create_order\n'
        "    raise KeyError('missing customer tier')\n"
        "KeyError: 'missing customer tier'\n"
    )

    # 1. Build normal context
    pkg = await builder.build_context(
        service="orders",
        incident_id="test-incident-123",
        error_trace=traceback_sample,
        token_budget=3500,
    )

    assert pkg.primary_service == "orders"
    assert pkg.incident_id == "test-incident-123"
    assert len(pkg.code_snippets) >= 1
    # Check that error site line 4 is covered
    first_snip = pkg.code_snippets[0]
    assert first_snip.start_line <= 4 <= first_snip.end_line
    assert not pkg.truncated
    assert pkg.estimated_tokens > 0

    # 2. Build with tight token budget to trigger truncation
    tight_pkg = await builder.build_context(
        service="orders",
        incident_id="test-incident-123",
        error_trace=traceback_sample,
        token_budget=50,  # Very small budget (200 characters)
    )

    assert tight_pkg.truncated

