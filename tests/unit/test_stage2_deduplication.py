"""Unit tests for in-batch deduplication and candidate builder."""
from datetime import datetime, timezone
from backend.clustering.candidate import deduplicate_log_batch


def test_deduplicate_batch_single_repeated_error():
    """100 repeated logs with varying order IDs and trace IDs must collapse to 1 candidate with count=100."""
    logs = [
        {
            "service": "orders",
            "level": "ERROR",
            "message": f"ZeroDivisionError: division by zero for ord-{i}",
            "error": {"error_code": "ZERO_DIVISION_ERROR"},
            "trace_id": f"trace-uuid-{i:04d}",
            "timestamp": f"2026-09-06T12:{i % 60:02d}:00Z",
        }
        for i in range(100)
    ]

    candidates = deduplicate_log_batch(logs)
    assert len(candidates) == 1

    candidate = candidates[0]
    assert candidate.occurrence_count == 100
    assert candidate.service_name == "orders"
    assert candidate.error_code == "ZERO_DIVISION_ERROR"
    assert len(candidate.sample_trace_ids) == 10  # Capped at 10 sample traces
    assert candidate.first_seen <= candidate.last_seen


def test_deduplicate_batch_multiple_distinct_errors():
    """Batch containing two distinct failure types produces exactly two candidates with preserved counts."""
    order_logs = [
        {
            "service": "orders",
            "level": "ERROR",
            "message": f"ZeroDivisionError for ord-{i}",
            "error": {"error_code": "ZERO_DIVISION_ERROR"},
            "trace_id": f"trace-order-{i}",
            "timestamp": "2026-09-06T12:00:00Z",
        }
        for i in range(40)
    ]

    payment_logs = [
        {
            "service": "payments",
            "level": "ERROR",
            "message": f"Payment processing timeout for tx-{i}",
            "error": {"error_code": "PAYMENT_TIMEOUT"},
            "trace_id": f"trace-pay-{i}",
            "timestamp": "2026-09-06T12:01:00Z",
        }
        for i in range(25)
    ]

    combined_logs = order_logs + payment_logs
    candidates = deduplicate_log_batch(combined_logs)

    assert len(candidates) == 2
    cand_by_svc = {c.service_name: c for c in candidates}
    assert "orders" in cand_by_svc
    assert "payments" in cand_by_svc

    assert cand_by_svc["orders"].occurrence_count == 40
    assert cand_by_svc["payments"].occurrence_count == 25


def test_deduplicate_batch_empty():
    assert deduplicate_log_batch([]) == []
