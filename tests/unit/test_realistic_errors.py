"""Unit tests for realistic error logging and machine-readable error codes."""
import pytest
from shared.schemas.log_event import LogEventSchema
from shared.logging.logger import StructuredEventLogger


def test_log_event_schema_with_error_code():
    """Verify LogEventSchema accepts and serializes error_code."""
    event = LogEventSchema(
        service_name="test-service",
        message="Division by zero in discount calculator",
        log_level="ERROR",
        event_type="calculation_error",
        error_code="ZERO_DIVISION_ERROR",
        attributes={"discount_code": "ZERO_SUBTOTAL"},
    )
    dumped = event.model_dump()
    assert dumped["error_code"] == "ZERO_DIVISION_ERROR"
    assert dumped["attributes"]["discount_code"] == "ZERO_SUBTOTAL"
    assert "ZERO_DIVISION_ERROR" in event.model_dump_json()


def test_structured_logger_captures_error_code():
    """Verify StructuredEventLogger extracts error_code from exception or attributes."""
    logger = StructuredEventLogger(service_name="orders")

    try:
        raise KeyError("PLATINUM")
    except KeyError as exc:
        event = logger._build_log_event(
            level="ERROR",
            message="Unhandled customer tier lookup",
            event_type="order_processing_error",
            error_code="KEY_ERROR",
            exception=exc,
            attributes={"tier": "PLATINUM"},
        )

    assert event.error_code == "KEY_ERROR"
    assert event.attributes["error_code"] == "KEY_ERROR"
    assert event.attributes["exception_type"] == "KeyError"
    assert "KeyError: 'PLATINUM'" in event.exception
    assert event.log_level == "ERROR"


def test_structured_logger_defaults_error_code_none_on_info():
    """Verify normal INFO logs default error_code to None."""
    logger = StructuredEventLogger(service_name="gateway")
    event = logger._build_log_event(
        level="INFO",
        message="Request processed successfully",
        event_type="http_response",
    )
    assert event.error_code is None
    assert "error_code" not in event.attributes
