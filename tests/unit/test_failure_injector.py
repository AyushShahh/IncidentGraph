"""Unit tests for FailureInjector configuration and simulation modes."""
import pytest
from fastapi import HTTPException
from shared.failures.injector import (
    FailureInjector,
    DatabaseTimeoutException,
    NetworkTimeoutException,
    RetryExhaustionException,
)


def test_failure_injector_default_zero_rate():
    """Verify that injector with 0.0 failure rate never raises."""
    injector = FailureInjector(service_name="test_svc", failure_rate=0.0)
    for _ in range(20):
        injector.inject_failure_if_needed("test_op")
    assert injector.call_count == 20


def test_failure_injector_database_timeout():
    """Verify database_timeout mode raises DatabaseTimeoutException."""
    injector = FailureInjector(service_name="test_svc", failure_rate=1.0, enabled_failures=["database_timeout"])
    with pytest.raises(DatabaseTimeoutException) as exc_info:
        injector.inject_failure_if_needed("query_orders")
    assert "Simulated DB timeout" in str(exc_info.value)


def test_failure_injector_network_timeout():
    """Verify network_timeout mode raises NetworkTimeoutException."""
    injector = FailureInjector(service_name="test_svc", failure_rate=1.0, enabled_failures=["network_timeout"])
    with pytest.raises(NetworkTimeoutException) as exc_info:
        injector.inject_failure_if_needed("fetch_upstream")
    assert "Simulated downstream connection timeout" in str(exc_info.value)


def test_failure_injector_http_500():
    """Verify http_500 mode raises HTTPException 500."""
    injector = FailureInjector(service_name="test_svc", failure_rate=1.0, enabled_failures=["http_500"])
    with pytest.raises(HTTPException) as exc_info:
        injector.inject_failure_if_needed("process_request")
    assert exc_info.value.status_code == 500
    assert "Internal Server Error" in str(exc_info.value.detail)


def test_failure_injector_authentication_failure():
    """Verify authentication_failure mode raises HTTPException 401."""
    injector = FailureInjector(service_name="test_svc", failure_rate=1.0, enabled_failures=["authentication_failure"])
    with pytest.raises(HTTPException) as exc_info:
        injector.inject_failure_if_needed("auth_check")
    assert exc_info.value.status_code == 401
    assert "Authentication Failure" in str(exc_info.value.detail)


def test_failure_injector_retry_exhaustion():
    """Verify retry_exhaustion mode raises RetryExhaustionException."""
    injector = FailureInjector(service_name="test_svc", failure_rate=1.0, enabled_failures=["retry_exhaustion"])
    with pytest.raises(RetryExhaustionException) as exc_info:
        injector.inject_failure_if_needed("dispatch_event")
    assert "Retry Exhaustion" in str(exc_info.value)


def test_failure_injector_trigger_after_n_calls():
    """Verify that failures are suppressed until trigger_after_n_calls threshold."""
    injector = FailureInjector(
        service_name="test_svc",
        failure_rate=1.0,
        enabled_failures=["database_timeout"],
        trigger_after_n_calls=3,
    )

    # First 3 calls pass
    injector.inject_failure_if_needed("op1")
    injector.inject_failure_if_needed("op2")
    injector.inject_failure_if_needed("op3")
    assert injector.call_count == 3

    # 4th call must fail
    with pytest.raises(DatabaseTimeoutException):
        injector.inject_failure_if_needed("op4")
    assert injector.call_count == 4


def test_failure_injector_dynamic_reconfiguration():
    """Verify dynamic update of failure rate and enabled modes."""
    injector = FailureInjector(service_name="test_svc", failure_rate=0.0)

    # Initially passes
    injector.inject_failure_if_needed("op")

    # Reconfigure to 100% failure with http_500
    injector.configure(failure_rate=1.0, enabled_failures=["http_500"])
    with pytest.raises(HTTPException) as exc:
        injector.inject_failure_if_needed("op")
    assert exc.value.status_code == 500


def test_failure_injector_health_ignored_without_target_operation():
    """Verify that health operation is never failed by generic failure simulation."""
    injector = FailureInjector(service_name="test_svc", failure_rate=1.0, enabled_failures=["http_500"])
    # Generic failure: health must not raise
    injector.inject_failure_if_needed("health")
    assert injector.call_count == 0  # Call count should not even increment for ignored health

    # But regular operation must fail
    with pytest.raises(HTTPException):
        injector.inject_failure_if_needed("checkout")


def test_failure_injector_health_fails_when_target_operation_is_health():
    """Verify that health operation fails when target_operation == 'health' is explicitly requested."""
    injector = FailureInjector(
        service_name="test_svc",
        failure_rate=1.0,
        enabled_failures=["http_500"],
        target_operation="health",
    )
    with pytest.raises(HTTPException) as exc:
        injector.inject_failure_if_needed("health")
    assert exc.value.status_code == 500

