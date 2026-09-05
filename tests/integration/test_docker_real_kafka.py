"""Real integration tests running against Docker Compose containers and real Kafka broker.

Verifies:
- Services communicate over HTTP
- Docker networking
- Kafka receives messages on service-logs
- Consumed messages validate against canonical LogEventSchema
- Failure logs are published with exception details
- Health endpoints across all services
"""
import asyncio
import json
import os
import uuid
import pytest
import httpx
from aiokafka import AIOKafkaConsumer

from shared.schemas.log_event import LogEventSchema

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8001")
ORDERS_URL = os.getenv("ORDERS_SERVICE_URL", "http://localhost:8002")
INVENTORY_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8004")
PAYMENTS_URL = os.getenv("PAYMENTS_SERVICE_URL", "http://localhost:8003")
NOTIFICATIONS_URL = os.getenv("NOTIFICATIONS_SERVICE_URL", "http://localhost:8005")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_LOGS_TOPIC = os.getenv("KAFKA_LOGS_TOPIC", "service-logs")


@pytest.mark.asyncio
async def test_all_services_health_endpoints_live():
    """Verify that all six services in Docker Compose respond healthy over real HTTP."""
    service_endpoints = {
        "gateway": f"{GATEWAY_URL}/health",
        "orders": f"{ORDERS_URL}/health",
        "inventory": f"{INVENTORY_URL}/health",
        "payments": f"{PAYMENTS_URL}/health",
        "notifications": f"{NOTIFICATIONS_URL}/health",
        "backend": f"{BACKEND_URL}/health",
    }

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for name, url in service_endpoints.items():
            resp = await client.get(url)
            assert resp.status_code == 200, f"Service '{name}' failed health check at {url}: {resp.status_code}"
            data = resp.json()
            assert data["status"] in ["ok", "healthy"]


@pytest.mark.asyncio
async def test_backend_readiness_probe():
    """Verify Backend readiness probe verifies Postgres, Redis, Kafka, and Qdrant connectivity."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{BACKEND_URL}/health/ready")
        assert resp.status_code == 200, f"Backend readiness probe failed: {resp.text}"
        data = resp.json()
        assert data["status"] == "ready"
        checks = data["checks"]
        assert checks["postgres"] == "ready"
        assert checks["redis"] == "ready"
        assert checks["kafka"] == "ready"
        assert checks["qdrant"] == "ready"


@pytest.mark.asyncio
async def test_real_kafka_receives_logs_and_validates_schema():
    """Verify that real Kafka broker receives messages from services and messages validate against LogEventSchema."""
    trace_id = f"trace-live-{uuid.uuid4().hex[:8]}"
    group_id = f"test-group-{uuid.uuid4().hex[:6]}"

    consumer = AIOKafkaConsumer(
        KAFKA_LOGS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    await consumer.start()

    try:
        # Give consumer a brief moment to assign partitions
        await asyncio.sleep(1.0)

        # Trigger realistic end-to-end checkout via Gateway
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/api/checkout",
                headers={"x-trace-id": trace_id},
                json={
                    "user_id": "test-kafka-user",
                    "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 25.0}],
                    "payment_method": "credit_card",
                },
            )
            assert resp.status_code == 200, f"Checkout failed: {resp.text}"

        # Consume messages from Kafka topic
        consumed_logs: list[dict] = []
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 8.0:
            try:
                batch = await asyncio.wait_for(consumer.getmany(timeout_ms=1000, max_records=20), timeout=2.0)
                for tp, messages in batch.items():
                    for msg in messages:
                        consumed_logs.append(msg.value)
            except asyncio.TimeoutError:
                pass

            # Check if we have logs for our trace_id
            trace_matches = [l for l in consumed_logs if l.get("trace_id") == trace_id]
            if len(trace_matches) >= 3:
                break

        assert len(consumed_logs) > 0, f"No logs consumed from topic '{KAFKA_LOGS_TOPIC}'"

        # Validate EVERY consumed log against the canonical LogEventSchema
        for raw in consumed_logs:
            validated = LogEventSchema.model_validate(raw)
            assert validated.timestamp is not None
            assert len(validated.service_name) > 0
            assert len(validated.instance_id) > 0
            assert len(validated.request_id) > 0
            assert len(validated.trace_id) > 0
            assert validated.log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            assert len(validated.event_type) > 0
            assert len(validated.message) > 0
            assert len(validated.deployment_version) > 0
            assert len(validated.environment) > 0

        # Validate trace correlation in Kafka logs
        matching_trace_logs = [l for l in consumed_logs if l.get("trace_id") == trace_id]
        assert len(matching_trace_logs) >= 2, f"Expected matching trace logs, found {len(matching_trace_logs)}"

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_real_failure_logs_received_in_kafka():
    """Verify that failure injection generates realistic ERROR logs in Kafka."""
    group_id = f"test-fail-group-{uuid.uuid4().hex[:6]}"
    fail_trace_id = f"trace-fail-{uuid.uuid4().hex[:8]}"

    consumer = AIOKafkaConsumer(
        KAFKA_LOGS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    await consumer.start()

    try:
        await asyncio.sleep(1.0)

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Send checkout request that triggers real zero division edge case
            fail_resp = await client.post(
                f"{GATEWAY_URL}/api/checkout",
                headers={"x-trace-id": fail_trace_id},
                json={
                    "user_id": "user-failure-test",
                    "items": [{"sku": "SKU-PROMO", "quantity": 1, "unit_price": 0.0}],
                    "discount_code": "ZERO_SUBTOTAL",
                },
            )
            assert fail_resp.status_code == 500

        # Consume from Kafka and look for error log
        consumed_logs: list[dict] = []
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 8.0:
            try:
                batch = await asyncio.wait_for(consumer.getmany(timeout_ms=1000, max_records=20), timeout=2.0)
                for tp, messages in batch.items():
                    for msg in messages:
                        consumed_logs.append(msg.value)
            except asyncio.TimeoutError:
                pass

            fail_logs = [
                l for l in consumed_logs
                if l.get("trace_id") == fail_trace_id and l.get("log_level") == "ERROR"
            ]
            if len(fail_logs) > 0:
                break

        matching_errors = [
            l for l in consumed_logs
            if l.get("trace_id") == fail_trace_id and l.get("log_level") == "ERROR"
        ]
        assert len(matching_errors) > 0, "Expected error log in Kafka for failed request"
        err_log = matching_errors[0]
        assert err_log["service_name"] == "gateway"
        assert err_log.get("error_code") == "ZeroDivisionError"
        assert "division by zero" in err_log.get("message", "")

    finally:
        await consumer.stop()
