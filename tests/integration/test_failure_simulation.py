"""Fast integration tests verifying failure simulation, error logs, and trigger thresholds."""
import pytest
from httpx import AsyncClient
from shared.failures.injector import get_shared_failure_injector
from shared.schemas.log_event import LogEventSchema


@pytest.mark.asyncio
async def test_failure_simulation_produces_error_logs(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that failure injection triggers error logs containing exception traces."""
    orders_injector = get_shared_failure_injector("orders")
    orders_injector.configure(failure_rate=1.0, enabled_failures=["http_500"])

    gw_client = service_network["gateway"]

    checkout_payload = {
        "user_id": "user-fail-test",
        "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 10.0}],
    }

    # Gateway should fail because Orders fails with HTTP 500
    resp = await gw_client.post("/api/checkout", json=checkout_payload)
    assert resp.status_code == 500

    # Find error log from failure simulation in kafka_spy
    error_logs = [log for log in kafka_spy if log.log_level == "ERROR"]
    assert len(error_logs) > 0

    sim_logs = [log for log in error_logs if log.event_type == "failure_simulation"]
    assert len(sim_logs) > 0
    assert sim_logs[0].service_name == "orders"
    assert sim_logs[0].attributes["failure_mode"] == "http_500"


@pytest.mark.asyncio
async def test_traffic_succeeds_before_failure_trigger_threshold(
    service_network: dict[str, AsyncClient],
):
    """Verify that traffic initially succeeds before trigger_after_n_calls threshold is reached."""
    gw_injector = get_shared_failure_injector("gateway")
    # First 2 calls must pass, 3rd call must fail
    gw_injector.configure(
        failure_rate=1.0,
        enabled_failures=["http_500"],
        trigger_after_n_calls=2,
    )

    gw_client = service_network["gateway"]
    payload = {
        "user_id": "user-threshold-test",
        "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 10.0}],
    }

    # Call 1: Success
    resp1 = await gw_client.post("/api/checkout", json=payload)
    assert resp1.status_code == 200

    # Call 2: Success
    resp2 = await gw_client.post("/api/checkout", json=payload)
    assert resp2.status_code == 200

    # Call 3: Failure
    resp3 = await gw_client.post("/api/checkout", json=payload)
    assert resp3.status_code == 500
