"""Unit tests for LogNormalizer dynamic variable stripping."""
import pytest
from backend.clustering.normalizer import LogNormalizer, normalizer


def test_normalizer_replaces_uuids():
    text = "Failed to process order 12345678-1234-5678-1234-567812345678 in payment gateway"
    normalized = normalizer.normalize(text)
    assert "<UUID>" in normalized
    assert "12345678-1234-5678-1234-567812345678" not in normalized


def test_normalizer_replaces_hex_addresses():
    text = "Segmentation fault at memory address 0x7fff5fbff8a0 in worker thread"
    normalized = normalizer.normalize(text)
    assert "<HEX>" in normalized
    assert "0x7fff5fbff8a0" not in normalized


def test_normalizer_replaces_ip_addresses():
    text = "Connection refused to upstream at 192.168.1.50:8080 timeout after 5000ms"
    normalized = normalizer.normalize(text)
    assert "<IP>" in normalized
    assert "192.168.1.50" not in normalized
    assert "<DURATION>" in normalized


def test_normalizer_replaces_timestamps():
    text = "Transaction error at 2026-09-06T12:00:00.123456Z: Database connection lost"
    normalized = normalizer.normalize(text)
    assert "<TIMESTAMP>" in normalized
    assert "2026-09-06T12:00:00.123456Z" not in normalized


def test_normalizer_replaces_domain_entity_ids():
    text = "Order ord-abc123xyz payment tx-987654 failed for user user-456 on item item-789"
    normalized = normalizer.normalize(text)
    assert "ord-<ID>" in normalized
    assert "tx-<ID>" in normalized
    assert "user-<ID>" in normalized
    assert "item-<ID>" in normalized
    assert "ord-abc123xyz" not in normalized


def test_normalizer_replaces_generic_prefixed_ids():
    text = "SKU-100 depleted in pod-checkout-42 on node-01"
    normalized = normalizer.normalize(text)
    assert "SKU-<ID>" in normalized
    assert "pod-<ID>" in normalized or "pod-checkout-<ID>" in normalized
    assert "node-<ID>" in normalized
    assert "SKU-100" not in normalized


def test_normalizer_replaces_quoted_literals_and_numbers():
    text = "KeyError: 'GBP' occurred; requested 5 items but available 0 (status 409 preserved)"
    normalized = normalizer.normalize(text)
    assert "'<LITERAL>'" in normalized
    assert "GBP" not in normalized
    assert "<NUM>" in normalized
    assert "409" in normalized  # HTTP status code preserved


def test_normalizer_replaces_traceback_line_numbers():
    text = 'Traceback (most recent call last): File "/app/services/orders/main.py", line 142, in create_order'
    normalized = normalizer.normalize(text)
    assert 'File "<FILE>", line <NUM>' in normalized
    assert "line 142" not in normalized


def test_extract_and_normalize_structured_log():
    log = {
        "service": "orders",
        "level": "ERROR",
        "message": "Failed to create order ord-9999 for user user-111",
        "error": {
            "type": "ZeroDivisionError",
            "message": "division by zero at 0xdeadbeef",
        },
        "event_type": "order_creation_failed",
    }
    normalized = LogNormalizer.extract_and_normalize(log)
    assert "ord-<ID>" in normalized
    assert "user-<ID>" in normalized
    assert "<HEX>" in normalized
    assert "division by zero" in normalized
