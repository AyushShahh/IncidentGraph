"""Unit tests for deterministic SHA256 fingerprint generation."""
from backend.clustering.fingerprint import generate_fingerprint, fingerprint_log
from backend.clustering.normalizer import normalizer


def test_fingerprint_deterministic_stability():
    """Verify that differing dynamic fields produce identical fingerprints after normalization."""
    raw_text_1 = "Failed to process order ord-1111 at 2026-09-06T10:00:00Z"
    raw_text_2 = "Failed to process order ord-2222 at 2026-09-06T11:30:00Z"

    norm_1 = normalizer.normalize(raw_text_1)
    norm_2 = normalizer.normalize(raw_text_2)
    assert norm_1 == norm_2

    fp1 = generate_fingerprint(
        service_name="orders",
        normalized_text=norm_1,
        error_code="ZERO_DIVISION_ERROR",
        endpoint="/orders",
        deployment_version="v1.0.0",
    )
    fp2 = generate_fingerprint(
        service_name="orders",
        normalized_text=norm_2,
        error_code="ZERO_DIVISION_ERROR",
        endpoint="/orders",
        deployment_version="v1.0.0",
    )
    assert fp1 == fp2
    assert len(fp1) == 64  # Valid SHA256 hex string


def test_fingerprint_differs_on_error_code():
    norm = "Database connection timeout"
    fp1 = generate_fingerprint("orders", norm, error_code="DB_TIMEOUT")
    fp2 = generate_fingerprint("orders", norm, error_code="CONNECTION_REFUSED")
    assert fp1 != fp2


def test_fingerprint_differs_on_service():
    norm = "Connection timeout after <DURATION>"
    fp1 = generate_fingerprint("orders", norm, error_code="TIMEOUT")
    fp2 = generate_fingerprint("payments", norm, error_code="TIMEOUT")
    assert fp1 != fp2


def test_fingerprint_log_helper():
    log1 = {
        "service": "orders",
        "error": {"error_code": "KEY_ERROR"},
        "event_type": "request_failed",
        "http": {"path": "/orders/checkout"},
        "deployment_version": "v1.0.0",
        "message": "KeyError: 'user_id' in ord-9999",
    }
    log2 = {
        "service": "orders",
        "error": {"error_code": "KEY_ERROR"},
        "event_type": "request_failed",
        "http": {"path": "/orders/checkout"},
        "deployment_version": "v1.0.0",
        "message": "KeyError: 'user_id' in ord-8888",
    }
    norm1 = normalizer.extract_and_normalize(log1)
    norm2 = normalizer.extract_and_normalize(log2)
    fp1 = fingerprint_log(log1, norm1)
    fp2 = fingerprint_log(log2, norm2)
    assert fp1 == fp2
