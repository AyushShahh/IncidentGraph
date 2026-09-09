"""Unit tests for Stage 3 in-memory symbol index and route registry."""
from backend.repository.schemas import RouteInfo, SymbolDefinition, SymbolType
from backend.repository.symbol_index import SymbolIndex


def test_symbol_index_registration_and_lookup():
    """Verify adding symbols, exact lookup, and qualified method resolution."""
    index = SymbolIndex()

    sym1 = SymbolDefinition(
        name="CheckoutRequest",
        symbol_type=SymbolType.CLASS,
        service_name="gateway",
        file_path="main.py",
        start_line=10,
        end_line=20,
    )
    sym2 = SymbolDefinition(
        name="OrderProcessor.execute",
        symbol_type=SymbolType.METHOD,
        service_name="orders",
        file_path="processor.py",
        start_line=30,
        end_line=45,
        docstring="Executes the order pipeline.",
    )
    sym3 = SymbolDefinition(
        name="checkout_route",
        symbol_type=SymbolType.ROUTE,
        service_name="gateway",
        file_path="main.py",
        start_line=50,
        end_line=65,
        route_info=RouteInfo(method="POST", path="/api/checkout", summary="Checkout API"),
    )

    index.add_symbols([sym1, sym2, sym3])

    # 1. Exact lookup
    res_cls = index.find_symbol("CheckoutRequest")
    assert len(res_cls) == 1
    assert res_cls[0].name == "CheckoutRequest"
    assert res_cls[0].service_name == "gateway"

    # 2. Qualified and base name lookup for method
    res_method_full = index.find_symbol("OrderProcessor.execute")
    assert len(res_method_full) == 1

    res_method_base = index.find_symbol("execute")
    assert len(res_method_base) == 1

    # 3. Route registration
    routes = index.get_service_routes("gateway")
    assert len(routes) == 1
    assert routes[0].path == "/api/checkout"
    assert routes[0].method == "POST"

    # 4. Search with filters
    search_cls = index.search_symbols("checkout", symbol_type=SymbolType.CLASS)
    assert len(search_cls) == 1
    assert search_cls[0].name == "CheckoutRequest"

    # 5. Remove service symbols
    index.remove_service_symbols("gateway")
    assert len(index.find_symbol("CheckoutRequest")) == 0
    assert len(index.get_service_routes("gateway")) == 0
    assert len(index.find_symbol("execute")) == 1
