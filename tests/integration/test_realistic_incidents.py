"""Integration tests verifying realistic edge cases, code bugs, and machine-readable error codes."""
import pytest
from httpx import AsyncClient
from shared.schemas.log_event import LogEventSchema


@pytest.mark.asyncio
async def test_checkout_zero_division_bug_produces_error_log(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that zero gross amount with promotional discount triggers ZeroDivisionError."""
    gw_client = service_network["gateway"]

    payload = {
        "user_id": "test-user-promo",
        "items": [{"sku": "SKU-PROMO", "quantity": 1, "unit_price": 0.0}],
        "discount_code": "ZERO_SUBTOTAL",
    }

    resp = await gw_client.post("/api/checkout", json=payload)
    assert resp.status_code == 500
    data = resp.json()
    assert data["error"] == "ZeroDivisionError"
    assert "division by zero" in data["detail"]

    # Verify Kafka log captures ZeroDivisionError with full traceback
    error_logs = [log for log in kafka_spy if log.log_level == "ERROR"]
    assert len(error_logs) > 0

    zero_div_logs = [l for l in error_logs if l.error_code == "ZeroDivisionError"]
    assert len(zero_div_logs) > 0
    assert zero_div_logs[0].service_name == "gateway"
    assert "division by zero" in zero_div_logs[0].message
    assert "ZeroDivisionError" in zero_div_logs[0].exception


@pytest.mark.asyncio
async def test_orders_unhandled_customer_tier_produces_key_error(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that unrecognized customer tier triggers unhandled KeyError in Orders."""
    orders_client = service_network["orders"]

    payload = {
        "user_id": "user-tier-platinum-999",  # "PLATINUM" tier not present in CUSTOMER_TIERS
        "items": [{"sku": "SKU-100", "quantity": 1}],
        "total_amount": 50.0,
    }

    resp = await orders_client.post("/orders", json=payload)
    assert resp.status_code == 500
    data = resp.json()
    assert data["error"] == "KeyError"

    # Verify Kafka log
    key_error_logs = [l for l in kafka_spy if l.error_code == "KeyError" and l.service_name == "orders"]
    assert len(key_error_logs) > 0
    assert "KeyError" in key_error_logs[0].exception


@pytest.mark.asyncio
async def test_inventory_batch_slicing_off_by_one_produces_index_error(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that bulk multi-item reservation triggers IndexError in batch slicing."""
    inv_client = service_network["inventory"]

    # 4 items triggers batching logic with off-by-one bug
    payload = {
        "items": [
            {"sku": "SKU-100", "quantity": 1},
            {"sku": "SKU-100", "quantity": 1},
            {"sku": "SKU-100", "quantity": 1},
            {"sku": "SKU-100", "quantity": 1},
        ]
    }

    resp = await inv_client.post("/inventory/reserve", json=payload)
    assert resp.status_code == 500
    data = resp.json()
    assert data["error"] == "IndexError"

    # Verify Kafka log
    index_error_logs = [l for l in kafka_spy if l.error_code == "IndexError" and l.service_name == "inventory"]
    assert len(index_error_logs) > 0
    assert "IndexError" in index_error_logs[0].exception


@pytest.mark.asyncio
async def test_payments_unhandled_currency_produces_key_error(
    service_network: dict[str, AsyncClient],
    kafka_spy: list[LogEventSchema],
):
    """Verify that unsupported currency triggers KeyError in exchange rate lookup."""
    payments_client = service_network["payments"]

    payload = {
        "user_id": "test-user-uk",
        "amount": 100.0,
        "currency": "GBP",  # "GBP" not in EXCHANGE_RATES dict
        "order_id": "ord-test-currency",
    }

    resp = await payments_client.post("/payments/charge", json=payload)
    assert resp.status_code == 500
    data = resp.json()
    assert data["error"] == "KeyError"

    # Verify Kafka log
    pay_key_errors = [l for l in kafka_spy if l.error_code == "KeyError" and l.service_name == "payments"]
    assert len(pay_key_errors) > 0
    assert "GBP" in pay_key_errors[0].exception


@pytest.mark.asyncio
async def test_natural_business_payment_declined_and_out_of_stock(
    service_network: dict[str, AsyncClient],
):
    """Verify natural business rejections return proper 4xx codes with machine-readable error codes."""
    gw_client = service_network["gateway"]

    # 1. Payment declined
    declined_payload = {
        "user_id": "test-user-card",
        "items": [{"sku": "SKU-100", "quantity": 1, "unit_price": 20.0}],
        "payment_method": "card_declined",
    }
    resp1 = await gw_client.post("/api/checkout", json=declined_payload)
    assert resp1.status_code == 402
    assert resp1.headers.get("x-error-code") == "PAYMENT_DECLINED"

    # 2. Out of stock
    stockout_payload = {
        "user_id": "test-user-stock",
        "items": [{"sku": "SKU-OUT-OF-STOCK", "quantity": 1, "unit_price": 20.0}],
    }
    resp2 = await gw_client.post("/api/checkout", json=stockout_payload)
    assert resp2.status_code == 409
    assert resp2.headers.get("x-error-code") == "OUT_OF_STOCK"
