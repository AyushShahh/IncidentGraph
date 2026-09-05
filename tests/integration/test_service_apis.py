"""Fast integration tests verifying microservice APIs and inter-service coordination using ASGITransport."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_all_services_healthchecks(service_network: dict[str, AsyncClient]):
    """Verify that all five services respond on /health."""
    for service_name, client in service_network.items():
        resp = await client.get("/health")
        assert resp.status_code == 200, f"Service {service_name} failed health check: {resp.text}"
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == service_name


@pytest.mark.asyncio
async def test_inventory_reserve_and_check(service_network: dict[str, AsyncClient]):
    """Verify Inventory service reserve and stock check."""
    inv_client = service_network["inventory"]

    # Check initial stock
    resp = await inv_client.get("/inventory/SKU-100")
    assert resp.status_code == 200
    initial_qty = resp.json()["quantity"]

    # Reserve items
    res = await inv_client.post("/inventory/reserve", json={"items": [{"sku": "SKU-100", "quantity": 2}]})
    assert res.status_code == 200
    assert res.json()["status"] == "reserved"

    # Verify decremented stock
    check_resp = await inv_client.get("/inventory/SKU-100")
    assert check_resp.json()["quantity"] == initial_qty - 2


@pytest.mark.asyncio
async def test_notifications_dispatch_and_history(service_network: dict[str, AsyncClient]):
    """Verify Notifications service send and history lookup."""
    notif_client = service_network["notifications"]

    send_resp = await notif_client.post(
        "/notifications/send",
        json={
            "recipient": "user-42@example.com",
            "channel": "email",
            "subject": "Order Confirmed",
            "body": "Your order has been placed.",
        },
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["status"] == "sent"

    hist_resp = await notif_client.get("/notifications/history")
    assert hist_resp.status_code == 200
    assert hist_resp.json()["count"] >= 1


@pytest.mark.asyncio
async def test_payments_charge(service_network: dict[str, AsyncClient]):
    """Verify Payments service charge endpoint."""
    pay_client = service_network["payments"]

    charge_resp = await pay_client.post(
        "/payments/charge",
        json={
            "user_id": "cust-888",
            "amount": 149.99,
            "currency": "USD",
            "order_id": "ord-test-1",
        },
    )
    assert charge_resp.status_code == 200
    data = charge_resp.json()
    assert data["status"] == "CAPTURED"
    assert "transaction_id" in data


@pytest.mark.asyncio
async def test_gateway_checkout_end_to_end(service_network: dict[str, AsyncClient]):
    """Verify end-to-end checkout through Gateway -> Orders -> Inventory -> Payments -> Notifications."""
    gw_client = service_network["gateway"]

    checkout_payload = {
        "user_id": "user-1001",
        "items": [
            {"sku": "SKU-100", "quantity": 1, "unit_price": 25.0},
            {"sku": "SKU-200", "quantity": 2, "unit_price": 40.0},
        ],
        "payment_method": "credit_card",
    }

    resp = await gw_client.post("/api/checkout", json=checkout_payload)
    assert resp.status_code == 200, f"Checkout failed: {resp.text}"
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert "order" in body
    assert "payment" in body
    assert body["payment"]["amount"] == 105.0


@pytest.mark.asyncio
async def test_gateway_get_order_proxy_and_validation(service_network: dict[str, AsyncClient]):
    """Verify order lookup proxy and input validation via Gateway."""
    gw_client = service_network["gateway"]

    # 1. Validation error on empty items
    bad_resp = await gw_client.post("/api/checkout", json={"user_id": "user-test", "items": []})
    assert bad_resp.status_code == 400
    assert bad_resp.headers.get("x-error-code") == "EMPTY_ITEMS_LIST"

    # 2. Complete a valid order
    checkout_payload = {
        "user_id": "user-lookup-test",
        "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 50.0}],
    }
    resp = await gw_client.post("/api/checkout", json=checkout_payload)
    assert resp.status_code == 200
    order_id = resp.json()["order"]["order_id"]

    # 3. Retrieve order via gateway proxy
    lookup_resp = await gw_client.get(f"/api/orders/{order_id}")
    assert lookup_resp.status_code == 200
    assert lookup_resp.json()["order_id"] == order_id
    assert lookup_resp.json()["user_id"] == "user-lookup-test"
