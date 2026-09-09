"""Unit tests validating Stage 3 indexing directly on the real project microservices."""
from pathlib import Path
from unittest.mock import AsyncMock
import pytest

from backend.repository.dependency_graph import DependencyGraph
from backend.repository.discovery import RepositoryDiscovery
from backend.repository.indexer import RepositoryIndexer
from backend.repository.manifest import ManifestManager
from backend.repository.symbol_index import SymbolIndex


@pytest.mark.asyncio
async def test_real_services_indexing_and_topology(tmp_path: Path):
    """Index the actual services/ directory and verify extracted symbols, routes, and call edges."""
    services_root = Path("services").resolve()
    if not services_root.exists():
        pytest.skip("services/ directory not found in current environment")

    # Isolated test components
    manifest_dir = tmp_path / "manifests"
    discovery = RepositoryDiscovery(root_dirs=[str(services_root)])
    manifest_mgr = ManifestManager(storage_dir=str(manifest_dir))
    symbol_index = SymbolIndex()
    dependency_graph = DependencyGraph()
    mock_vector = AsyncMock()
    mock_vector.upsert_chunks = AsyncMock(return_value=10)
    mock_vector.delete_file_chunks = AsyncMock()

    indexer = RepositoryIndexer(
        discovery=discovery,
        manifest_mgr=manifest_mgr,
        symbol_index=symbol_index,
        dependency_graph=dependency_graph,
        vector_indexer=mock_vector,
    )

    # 1. Index all services
    res = await indexer.index_all_repositories(force=True)
    assert res["status"] == "completed"
    assert "gateway" in res["indexed_services"]
    assert "orders" in res["indexed_services"]
    assert "inventory" in res["indexed_services"]
    assert "payments" in res["indexed_services"]
    assert "notifications" in res["indexed_services"]

    # 2. Verify symbol resolution on real services
    checkout_syms = symbol_index.search_symbols("checkout", service="gateway")
    assert len(checkout_syms) >= 1
    sym_names = {s.name for s in checkout_syms}
    assert "checkout" in sym_names or "CheckoutRequest" in sym_names

    # 3. Verify real exposed routes
    routes = symbol_index.get_all_routes()
    assert "gateway" in routes
    assert any(r.path == "/api/checkout" for r in routes["gateway"])
    assert "orders" in routes
    assert any(r.path == "/orders" for r in routes["orders"])
    assert "inventory" in routes
    assert any(r.path == "/inventory/reserve" for r in routes["inventory"])
    assert "payments" in routes
    assert any(r.path == "/payments/charge" for r in routes["payments"])
    assert "notifications" in routes
    assert any(r.path == "/notifications/send" for r in routes["notifications"])

    # 4. Verify inter-service dependency edges in the directed graph
    # gateway calls orders and payments
    gw_deps = dependency_graph.get_dependencies("gateway")
    assert "orders" in gw_deps
    assert "payments" in gw_deps

    # orders calls inventory and notifications
    ord_deps = dependency_graph.get_dependencies("orders")
    assert "inventory" in ord_deps
    assert "notifications" in ord_deps

    # payments calls notifications
    pay_deps = dependency_graph.get_dependencies("payments")
    assert "notifications" in pay_deps

    # 5. Verify blast radius on inventory
    # direct callers: orders
    # transitive callers: orders, gateway
    radius_inv = dependency_graph.get_blast_radius("inventory")
    assert "orders" in radius_inv.direct_callers
    assert "gateway" in radius_inv.transitive_callers
    assert radius_inv.impact_level in ("HIGH", "CRITICAL")

    # 6. Test second run with force=False (relying on manifests on disk)
    # Even when manifests exist on disk, in-memory symbols and graph must remain 100% populated!
    res2 = await indexer.index_all_repositories(force=False)
    assert res2["status"] == "completed"

    checkout_syms2 = symbol_index.search_symbols("checkout", service="gateway")
    assert len(checkout_syms2) >= 1

    gw_deps2 = dependency_graph.get_dependencies("gateway")
    assert "orders" in gw_deps2
    assert "payments" in gw_deps2
