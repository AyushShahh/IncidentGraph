"""Unit tests for canonical LogEventSchema validation and serialization."""
from datetime import datetime, timezone
import json
import pytest
from pydantic import ValidationError
from shared.schemas.log_event import LogEventSchema


def test_log_event_schema_all_15_fields():
    """Verify that all 15 required canonical fields instantiate and serialize properly."""
    now = datetime.now(timezone.utc)
    event = LogEventSchema(
        timestamp=now,
        service_name="orders",
        instance_id="inst-node-01",
        request_id="req-12345",
        trace_id="trace-67890",
        session_id="sess-abc",
        log_level="ERROR",
        event_type="db_query",
        message="Database connection pool timeout",
        error_code="DB_POOL_TIMEOUT",
        exception="ConnectionTimeoutException: Unable to acquire connection within 5000ms",
        attributes={"pool_size": 20, "active_connections": 20},
        upstream_service="gateway",
        downstream_service="postgres",
        deployment_version="v2.1.0",
        environment="production",
    )

    # Validate model fields
    assert event.service_name == "orders"
    assert event.instance_id == "inst-node-01"
    assert event.request_id == "req-12345"
    assert event.trace_id == "trace-67890"
    assert event.session_id == "sess-abc"
    assert event.log_level == "ERROR"
    assert event.event_type == "db_query"
    assert event.error_code == "DB_POOL_TIMEOUT"
    assert event.message == "Database connection pool timeout"
    assert event.exception is not None
    assert event.upstream_service == "gateway"
    assert event.downstream_service == "postgres"
    assert event.deployment_version == "v2.1.0"
    assert event.environment == "production"
    assert event.attributes["pool_size"] == 20

    # Validate JSON serialization contains all keys
    serialized = json.loads(event.model_dump_json())
    canonical_keys = [
        "timestamp",
        "service_name",
        "instance_id",
        "request_id",
        "trace_id",
        "session_id",
        "log_level",
        "event_type",
        "error_code",
        "message",
        "exception",
        "attributes",
        "upstream_service",
        "downstream_service",
        "deployment_version",
        "environment",
    ]
    for key in canonical_keys:
        assert key in serialized, f"Missing field '{key}' in serialized log JSON"


def test_log_event_schema_defaults():
    """Verify default values for instance_id, IDs, timestamp, version, and environment."""
    event = LogEventSchema(
        service_name="payments",
        message="Card charged successfully",
    )

    assert event.service_name == "payments"
    assert event.message == "Card charged successfully"
    assert event.log_level == "INFO"
    assert event.deployment_version == "v1.0.0"
    assert event.environment == "development"
    assert len(event.instance_id) > 0
    assert len(event.request_id) > 0
    assert len(event.trace_id) > 0
    assert event.exception is None
    assert event.session_id is None
    assert event.upstream_service is None
    assert event.downstream_service is None
    assert isinstance(event.attributes, dict)


def test_log_event_schema_missing_service_name_raises():
    """Verify that omitting service_name causes validation error."""
    with pytest.raises(ValidationError):
        LogEventSchema(message="Missing service")


def test_log_event_schema_missing_message_raises():
    """Verify that omitting message causes validation error."""
    with pytest.raises(ValidationError):
        LogEventSchema(service_name="orders")
