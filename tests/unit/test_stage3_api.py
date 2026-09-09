import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.router import api_router
from backend.repository.dependency_graph import get_dependency_graph
from backend.repository.indexer import get_repository_indexer
from backend.repository.schemas import RouteInfo, SymbolDefinition, SymbolType
from backend.repository.symbol_index import get_symbol_index


def get_test_app() -> FastAPI:
    """Create isolated FastAPI app mounting api_router."""
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture(autouse=True)
def setup_test_index():
    """Seed test data into repository engine singletons."""
    symbol_index = get_symbol_index()
    dep_graph = get_dependency_graph()
    indexer = get_repository_indexer()

    symbol_index.add_symbols([
        SymbolDefinition(
            name="checkout",
            symbol_type=SymbolType.ROUTE,
            service_name="gateway",
            file_path="main.py",
            start_line=40,
            end_line=60,
            route_info=RouteInfo(method="POST", path="/api/checkout", summary="Checkout endpoint"),
        ),
        SymbolDefinition(
            name="reserve_stock",
            symbol_type=SymbolType.FUNCTION,
            service_name="inventory",
            file_path="main.py",
            start_line=20,
            end_line=35,
        ),
    ])

    dep_graph.add_service_node("gateway", [RouteInfo(method="POST", path="/api/checkout")])
    dep_graph.add_service_node("orders", [RouteInfo(method="POST", path="/orders")])
    dep_graph.add_service_node("inventory", [RouteInfo(method="POST", path="/inventory/reserve")])

    yield


@pytest.mark.asyncio
async def test_api_repositories_list_and_status():
    """Verify GET /api/v1/repositories and /api/v1/repositories/status."""
    app = get_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. List repositories
        res_list = await client.get("/api/v1/repositories")
        assert res_list.status_code == 200
        data_list = res_list.json()
        assert "total_repositories" in data_list
        assert "repositories" in data_list

        # 2. Status
        res_status = await client.get("/api/v1/repositories/status")
        assert res_status.status_code == 200
        data_status = res_status.json()
        assert "is_indexing" in data_status
        assert "total_symbols" in data_status


@pytest.mark.asyncio
async def test_api_dependency_graph_and_blast_radius():
    """Verify GET /api/v1/repositories/dependency-graph and /blast-radius/{service}."""
    app = get_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Graph topology
        res_graph = await client.get("/api/v1/repositories/dependency-graph")
        assert res_graph.status_code == 200
        data_graph = res_graph.json()
        assert "total_nodes" in data_graph
        assert "nodes" in data_graph
        assert "edges" in data_graph

        # 2. Blast radius
        res_radius = await client.get("/api/v1/repositories/blast-radius/inventory")
        assert res_radius.status_code == 200
        data_radius = res_radius.json()
        assert data_radius["target_service"] == "inventory"
        assert "impact_level" in data_radius
        assert "summary" in data_radius


@pytest.mark.asyncio
async def test_api_symbol_search():
    """Verify GET /api/v1/repositories/symbols/search."""
    app = get_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/repositories/symbols/search?query=checkout")
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 1
        assert data[0]["name"] == "checkout"
        assert data[0]["service_name"] == "gateway"


@pytest.mark.asyncio
async def test_api_context_build():
    """Verify POST /api/v1/context/build."""
    app = get_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "service": "gateway",
            "incident_id": "test-inc-456",
            "error_trace": "ZeroDivisionError: division by zero",
            "token_budget": 2000,
        }
        res = await client.post("/api/v1/context/build", json=payload)
        assert res.status_code == 200
        data = res.json()
        # Test with primary_service and max_tokens aliases
        alt_payload = {
            "primary_service": "gateway",
            "incident_id": "test-inc-789",
            "error_message": "ZeroDivisionError: division by zero",
            "max_tokens": 1500,
        }
        res_alt = await client.post("/api/v1/context/build", json=alt_payload)
        assert res_alt.status_code == 200
        alt_data = res_alt.json()
        assert alt_data["primary_service"] == "gateway"
        assert alt_data["token_budget"] == 1500

        # Routes endpoint
        res_routes = await client.get("/api/v1/repositories/routes/gateway")
        assert res_routes.status_code == 200
        assert len(res_routes.json()) >= 1

