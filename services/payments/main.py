"""Payments microservice processing payment authorizations and charges."""
from contextlib import asynccontextmanager
import os
from typing import Any, AsyncGenerator
import uuid
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.logging.middleware import TraceCorrelationMiddleware
from shared.logging.logger import get_service_logger
from shared.kafka.producer import get_shared_kafka_producer
from shared.http_client import ServiceHttpClient

SERVICE_NAME = "payments"

logger = get_service_logger(SERVICE_NAME)
http_client = ServiceHttpClient(caller_service=SERVICE_NAME)

NOTIFICATIONS_SERVICE_URL = os.getenv("NOTIFICATIONS_SERVICE_URL", "http://notifications:8005")

# Supported exchange rates against base USD
EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 0.92,
}

TRANSACTIONS: dict[str, dict[str, Any]] = {}

# Test override client hook for ASGITransport testing
target_service_clients: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    producer = get_shared_kafka_producer()
    try:
        await producer.start()
        logger.info("Payments service initialized and connected to Kafka.")
    except Exception as exc:
        logger.warning("Kafka producer connection deferred or failed: %s", exc)

    yield

    await http_client.close()
    await producer.stop()
    logger.info("Payments service shut down cleanly.")


app = FastAPI(title="Payments Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(TraceCorrelationMiddleware, service_name=SERVICE_NAME)


class ChargeRequest(BaseModel):
    user_id: str
    amount: float = Field(..., ge=0)
    currency: str = Field(default="USD")
    order_id: str
    payment_method: str = Field(default="credit_card")


@app.get("/health")
async def health():
    """Service healthcheck."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/payments/charge")
async def charge_payment(payload: ChargeRequest):
    """Authorize and capture customer payment."""
    # 1. Natural business validation: Payment declines & limits
    if payload.payment_method == "card_declined":
        logger.warning(
            f"Payment authorization declined for user {payload.user_id} on order {payload.order_id}",
            event_type="payment_declined",
            error_code="PAYMENT_DECLINED",
            attributes={"order_id": payload.order_id, "amount": payload.amount},
        )
        raise HTTPException(
            status_code=402,
            detail="Payment authorization declined by issuing bank: DO_NOT_HONOR",
            headers={"x-error-code": "PAYMENT_DECLINED"},
        )

    if payload.amount > 5000.0:
        logger.warning(
            f"Transaction limit exceeded for user {payload.user_id}: amount ${payload.amount:.2f}",
            event_type="payment_limit_exceeded",
            error_code="TRANSACTION_LIMIT_EXCEEDED",
            attributes={"order_id": payload.order_id, "amount": payload.amount},
        )
        raise HTTPException(
            status_code=402,
            detail=f"Transaction amount ${payload.amount:.2f} exceeds maximum single charge limit of $5000.00",
            headers={"x-error-code": "TRANSACTION_LIMIT_EXCEEDED"},
        )

    # Currency exchange rate thing
    rate = EXCHANGE_RATES[payload.currency]
    usd_amount = round(payload.amount * rate, 2)

    tx_id = f"tx-{uuid.uuid4().hex[:8]}"
    record = {
        "transaction_id": tx_id,
        "user_id": payload.user_id,
        "amount": payload.amount,
        "usd_equivalent": usd_amount,
        "currency": payload.currency,
        "order_id": payload.order_id,
        "payment_method": payload.payment_method,
        "status": "CAPTURED",
    }
    TRANSACTIONS[tx_id] = record

    logger.info(
        f"Payment of {payload.amount} {payload.currency} captured for user {payload.user_id}",
        event_type="payment_processed",
        attributes={"transaction_id": tx_id, "amount": payload.amount, "currency": payload.currency},
    )

    # Trigger notification receipt
    notif_client = target_service_clients.get("notifications")
    try:
        await http_client.post(
            url=f"{NOTIFICATIONS_SERVICE_URL}/notifications/send",
            target_service="notifications",
            json_data={
                "recipient": payload.user_id,
                "subject": "Payment Receipt",
                "body": f"Your payment of {payload.amount:.2f} {payload.currency} was processed successfully.",
                "channel": "email",
                "order_id": payload.order_id,
            },
            client=notif_client,
        )
    except Exception as exc:
        logger.warning(
            f"Failed to dispatch payment notification: {exc}",
            event_type="notification_failed",
            attributes={"error": str(exc)},
        )

    return record


@app.get("/payments/{payment_id}")
async def get_payment(payment_id: str):
    """Retrieve transaction record by ID."""
    record = TRANSACTIONS.get(payment_id)
    if not record:
        logger.warning(
            f"Transaction {payment_id} not found",
            event_type="payment_not_found",
            error_code="TRANSACTION_NOT_FOUND",
            attributes={"transaction_id": payment_id},
        )
        raise HTTPException(
            status_code=404,
            detail="Transaction not found",
            headers={"x-error-code": "TRANSACTION_NOT_FOUND"},
        )
    return record
