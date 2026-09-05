"""Integration tests verifying distributed trace ID, request ID, and session ID propagation across microservices."""
import pytest
from httpx import AsyncClient
from shared.schemas.log_event import LogEventSchema


@pytest.mark.asyncio
async def test_trace_id_propagates_across_all_five_services(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that an explicit trace_id initiated at Gateway is propagated through all 5 microservices."""
    gw_client = service_network["gateway"]

    custom_trace_id = "trace-e2e-abc-12345"
    custom_request_id = "req-e2e-xyz-67890"
    custom_session_id = "session-cust-99"

    headers = {
        "x-trace-id": custom_trace_id,
        "x-request-id": custom_request_id,
        "x-session-id": custom_session_id,
    }

    checkout_payload = {
        "user_id": "cust-trace-test",
        "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 50.0}],
        "payment_method": "credit_card",
    }

    response = await gw_client.post("/api/checkout", json=checkout_payload, headers=headers)
    assert response.status_code == 200, f"Checkout failed: {response.text}"

    # Response must echo back tracing IDs
    assert response.headers["x-trace-id"] == custom_trace_id
    assert response.headers["x-request-id"] == custom_request_id
    assert response.headers.get("x-session-id") == custom_session_id

    # Filter logs matching this trace_id
    trace_logs = [log for log in kafka_spy if log.trace_id == custom_trace_id]
    assert len(trace_logs) >= 5, f"Expected at least 5 logs across 5 services, found {len(trace_logs)}"

    # Verify all 5 services participated in this trace
    services_logged = {log.service_name for log in trace_logs}
    for svc in ["gateway", "orders", "inventory", "payments", "notifications"]:
        assert svc in services_logged, f"Expected service '{svc}' to log with trace_id {custom_trace_id}"

    # Verify upstream service tracking
    orders_logs = [log for log in trace_logs if log.service_name == "orders" and log.event_type == "http_request"]
    assert len(orders_logs) > 0
    assert orders_logs[0].upstream_service == "gateway"

    inventory_logs = [log for log in trace_logs if log.service_name == "inventory" and log.event_type == "http_request"]
    assert len(inventory_logs) > 0
    assert inventory_logs[0].upstream_service == "orders"

    payments_logs = [log for log in trace_logs if log.service_name == "payments" and log.event_type == "http_request"]
    assert len(payments_logs) > 0
    assert payments_logs[0].upstream_service == "gateway"


@pytest.mark.asyncio
async def test_auto_generated_trace_id_propagation(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify middleware generates trace_id when none provided and propagates across all hops."""
    gw_client = service_network["gateway"]

    checkout_payload = {
        "user_id": "cust-auto-trace",
        "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 30.0}],
    }

    # Request without explicit tracing headers
    response = await gw_client.post("/api/checkout", json=checkout_payload)
    assert response.status_code == 200

    generated_trace_id = response.headers.get("x-trace-id")
    assert generated_trace_id is not None
    assert len(generated_trace_id) > 0

    generated_req_id = response.headers.get("x-request-id")
    assert generated_req_id is not None
    assert len(generated_req_id) > 0

    matched_logs = [log for log in kafka_spy if log.trace_id == generated_trace_id]
    assert len(matched_logs) >= 5

    # Confirm all downstream services share this auto-generated trace ID
    services_in_trace = {log.service_name for log in matched_logs}
    assert {"gateway", "orders", "payments", "inventory", "notifications"}.issubset(services_in_trace)
