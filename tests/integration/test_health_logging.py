"""Tests verifying health check noise reduction, failure logging, and business log preservation."""
import pytest
from httpx import AsyncClient
from shared.failures.injector import get_shared_failure_injector
from shared.schemas.log_event import LogEventSchema


@pytest.mark.asyncio
async def test_successful_health_checks_do_not_publish_kafka_logs(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that successful /health checks across all services do NOT emit Kafka logs."""
    for service_name, client in service_network.items():
        resp = await client.get("/health")
        assert resp.status_code == 200, f"Service {service_name} /health returned {resp.status_code}"
        assert resp.json()["status"] == "ok"

    # Kafka spy must remain completely empty - zero health noise
    assert len(kafka_spy) == 0, f"Expected 0 Kafka logs for successful health checks, but got {len(kafka_spy)}"


@pytest.mark.asyncio
async def test_failed_health_check_publishes_error_log(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that failed health checks (4xx, 5xx, or exception) DO publish ERROR logs to Kafka."""
    gw_injector = get_shared_failure_injector("gateway")
    gw_injector.configure(
        failure_rate=1.0,
        enabled_failures=["http_500"],
        trigger_after_n_calls=0,
        target_operation="health",
    )

    gw_client = service_network["gateway"]
    resp = await gw_client.get("/health")
    assert resp.status_code == 500

    # Must produce a health_check_failed ERROR log in Kafka for incident signal
    health_errors = [log for log in kafka_spy if log.event_type == "health_check_failed"]
    assert len(health_errors) > 0, "Failed health check must emit an ERROR log to Kafka"
    
    health_error = health_errors[0]
    assert health_error.log_level == "ERROR"
    assert health_error.service_name == "gateway"
    assert health_error.attributes["status_code"] == 500

    # Reset injector
    gw_injector.configure(failure_rate=0.0, trigger_after_n_calls=0)
    gw_injector.reset_counts()


@pytest.mark.asyncio
async def test_health_check_ignores_generic_business_failure_simulation(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that generic failure simulation (e.g. on checkout) does NOT cause /health to fail."""
    gw_injector = get_shared_failure_injector("gateway")
    # Simulate 100% failure rate without target_operation="health"
    gw_injector.configure(
        failure_rate=1.0,
        enabled_failures=["http_500"],
        trigger_after_n_calls=0,
    )

    gw_client = service_network["gateway"]
    
    # /health must remain 200 OK (Docker healthcheck will NOT fail)
    resp = await gw_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert len(kafka_spy) == 0

    # But business endpoint /api/checkout MUST fail with 500
    checkout_payload = {
        "user_id": "test-user-fail",
        "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 25.0}],
    }
    biz_resp = await gw_client.post("/api/checkout", json=checkout_payload)
    assert biz_resp.status_code == 500

    # Reset injector
    gw_injector.configure(failure_rate=0.0, trigger_after_n_calls=0)
    gw_injector.reset_counts()


@pytest.mark.asyncio
async def test_business_requests_still_produce_kafka_logs(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that business requests (e.g., checkout) continue producing structured Kafka logs."""
    gw_client = service_network["gateway"]
    payload = {
        "user_id": "user-biz-log-test",
        "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 30.0}],
    }

    resp = await gw_client.post("/api/checkout", json=payload)
    assert resp.status_code == 200

    # Business request must produce logs across services
    assert len(kafka_spy) >= 5, f"Expected at least 5 logs across microservices, found {len(kafka_spy)}"
    services_logged = {log.service_name for log in kafka_spy}
    assert "gateway" in services_logged
    assert "orders" in services_logged


@pytest.mark.asyncio
async def test_trace_headers_preserved_on_health_checks(
    service_network: dict[str, AsyncClient],
):
    """Verify that distributed trace correlation headers are still preserved on health checks."""
    gw_client = service_network["gateway"]
    custom_trace_id = "trace-health-probe-123"
    custom_request_id = "req-health-probe-456"

    headers = {
        "x-trace-id": custom_trace_id,
        "x-request-id": custom_request_id,
    }

    resp = await gw_client.get("/health", headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("x-trace-id") == custom_trace_id
    assert resp.headers.get("x-request-id") == custom_request_id
