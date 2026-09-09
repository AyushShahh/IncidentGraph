"""Unit tests for Stage 3 dynamic dependency graph and blast radius engine."""
from backend.repository.dependency_graph import DependencyGraph
from backend.repository.parser import OutboundCallInfo
from backend.repository.schemas import DependencyEdge, DependencyEdgeType, RouteInfo


def test_arbitrary_services_dependency_graph():
    """Verify the dependency graph works for arbitrary services without any hardcoding."""
    graph = DependencyGraph()

    # Define arbitrary services: svc_frontend -> svc_auth -> svc_user_db
    services = ["svc_frontend", "svc_auth", "svc_user_db"]
    routes = {
        "svc_auth": [RouteInfo(method="POST", path="/api/v1/auth/login")],
        "svc_user_db": [RouteInfo(method="GET", path="/users/{user_id}")],
    }
    outbound = [
        OutboundCallInfo(
            caller_service="svc_frontend",
            caller_file="app.py",
            line_no=25,
            call_type="http",
            target_service_hint="svc_auth",
            target_url_or_path="http://svc_auth:8080/api/v1/auth/login",
            http_method="POST",
        ),
        OutboundCallInfo(
            caller_service="svc_auth",
            caller_file="client.py",
            line_no=40,
            call_type="http",
            target_service_hint="svc_user_db",
            target_url_or_path="http://svc_user_db:5000/users/1",
            http_method="GET",
        ),
    ]

    graph.build_from_parsed_data(
        service_names=services,
        service_routes=routes,
        outbound_calls=outbound,
    )

    # Verify downstream dependencies
    assert graph.get_dependencies("svc_frontend") == ["svc_auth"]
    assert graph.get_dependencies("svc_auth") == ["svc_user_db"]
    assert graph.get_dependencies("svc_user_db") == []

    # Verify upstream callers
    assert graph.get_dependents("svc_user_db") == ["svc_auth"]
    assert graph.get_dependents("svc_auth") == ["svc_frontend"]
    assert graph.get_dependents("svc_frontend") == []


def test_blast_radius_transitive_impact():
    """Verify blast radius calculates upstream callers (ancestors) if a leaf service fails."""
    graph = DependencyGraph()

    # Topology: gateway -> orders -> inventory
    #           gateway -> payments
    services = ["gateway", "orders", "inventory", "payments"]
    routes = {
        "orders": [RouteInfo(method="POST", path="/orders")],
        "inventory": [RouteInfo(method="POST", path="/inventory/reserve")],
        "payments": [RouteInfo(method="POST", path="/payments/charge")],
    }
    outbound = [
        OutboundCallInfo(caller_service="gateway", caller_file="main.py", line_no=10, call_type="http", target_service_hint="orders"),
        OutboundCallInfo(caller_service="gateway", caller_file="main.py", line_no=20, call_type="http", target_service_hint="payments"),
        OutboundCallInfo(caller_service="orders", caller_file="main.py", line_no=30, call_type="http", target_service_hint="inventory"),
    ]

    graph.build_from_parsed_data(services, routes, outbound)

    # 1. Test failure in leaf: inventory
    # Direct caller: orders
    # Transitive callers: orders, gateway
    radius_inv = graph.get_blast_radius("inventory")
    assert radius_inv.target_service == "inventory"
    assert radius_inv.direct_callers == ["orders"]
    assert set(radius_inv.transitive_callers) == {"orders", "gateway"}
    assert radius_inv.downstream_dependencies == []
    assert radius_inv.impact_level in ("HIGH", "CRITICAL")
    assert len(radius_inv.affected_routes) >= 2

    # 2. Test failure in edge caller: gateway
    radius_gw = graph.get_blast_radius("gateway")
    assert radius_gw.direct_callers == []
    assert radius_gw.transitive_callers == []
    assert set(radius_gw.downstream_dependencies) == {"orders", "payments"}
    assert radius_gw.impact_level == "LOW"


def test_full_topology_export():
    """Verify graph serialization into nodes, edges, and centralities."""
    graph = DependencyGraph()
    graph.add_dependency_edge(
        DependencyEdge(
            source_service="client",
            target_service="server",
            edge_type=DependencyEdgeType.HTTP,
            method="GET",
            endpoint="/health",
        )
    )

    topo = graph.get_full_topology()
    assert topo["total_nodes"] == 2
    assert topo["total_edges"] == 1
    assert any(n["service_name"] == "server" for n in topo["nodes"])
    assert any(e["source"] == "client" and e["target"] == "server" for e in topo["edges"])
