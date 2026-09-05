"""Payments microservice for processing charges and transactions."""
from contextlib import asynccontextmanager
import os
from typing import Any, AsyncGenerator
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.logging.middleware import TraceCorrelationMiddleware
from shared.logging.logger import get_service_logger
from shared.kafka.producer import get_shared_kafka_producer
from shared.failures.injector import (
    get_shared_failure_injector,
    FailureConfigRequest,
    DatabaseTimeoutException,
    NetworkTimeoutException,
    RetryExhaustionException,
)
from shared.http_client import ServiceHttpClient

SERVICE_NAME = "payments"

logger = get_service_logger(SERVICE_NAME)
failure_injector = get_shared_failure_injector(SERVICE_NAME)
http_client = ServiceHttpClient(caller_service=SERVICE_NAME)

NOTIFICATIONS_SERVICE_URL = os.getenv("NOTIFICATIONS_SERVICE_URL", "http://notifications:8005")

# In-memory transaction storage
TRANSACTIONS: dict[str, dict[str, Any]] = {}

# Test override client hook
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


@app.exception_handler(DatabaseTimeoutException)
async def db_timeout_handler(request: Request, exc: DatabaseTimeoutException):
    return JSONResponse(status_code=504, content={"detail": str(exc), "error": "database_timeout"})


@app.exception_handler(NetworkTimeoutException)
async def net_timeout_handler(request: Request, exc: NetworkTimeoutException):
    return JSONResponse(status_code=504, content={"detail": str(exc), "error": "network_timeout"})


@app.exception_handler(RetryExhaustionException)
async def retry_exhaust_handler(request: Request, exc: RetryExhaustionException):
    return JSONResponse(status_code=503, content={"detail": str(exc), "error": "retry_exhaustion"})


class ChargeRequest(BaseModel):
    user_id: str
    amount: float = Field(..., gt=0)
    currency: str = Field(default="USD")
    order_id: str


@app.get("/health")
async def health():
    """Service healthcheck."""
    failure_injector.inject_failure_if_needed("health")
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/simulate-failure")
async def configure_failure(payload: FailureConfigRequest):
    """Configure failure injector settings at runtime."""
    failure_injector.configure(
        failure_rate=payload.failure_rate,
        enabled_failures=payload.enabled_failures,
        trigger_after_n_calls=payload.trigger_after_n_calls,
        target_operation=payload.target_operation,
    )
    return {
        "status": "updated",
        "service": SERVICE_NAME,
        "target_operation": failure_injector.target_operation,
        "failure_rate": failure_injector.failure_rate,
        "enabled_failures": failure_injector.enabled_failures,
        "trigger_after_n_calls": failure_injector.trigger_after_n_calls,
    }


@app.get("/simulate-failure")
async def get_failure_config():
    """Return current failure injector settings."""
    return {
        "service": SERVICE_NAME,
        "failure_rate": failure_injector.failure_rate,
        "enabled_failures": failure_injector.enabled_failures,
        "calls_recorded": failure_injector.call_count,
        "trigger_after_n_calls": failure_injector.trigger_after_n_calls,
    }


@app.post("/payments/charge")
async def charge_payment(payload: ChargeRequest):
    """Authorize and capture customer payment."""
    failure_injector.inject_failure_if_needed("charge_payment")

    tx_id = f"tx-{uuid.uuid4().hex[:8]}"
    record = {
        "transaction_id": tx_id,
        "user_id": payload.user_id,
        "amount": payload.amount,
        "currency": payload.currency,
        "order_id": payload.order_id,
        "status": "CAPTURED",
    }
    TRANSACTIONS[tx_id] = record

    logger.info(
        f"Payment of {payload.amount} {payload.currency} captured for user {payload.user_id}",
        event_type="payment_processed",
        attributes={"transaction_id": tx_id, "amount": payload.amount},
    )

    # Trigger notification
    notif_client = target_service_clients.get("notifications")
    try:
        await http_client.post(
            url=f"{NOTIFICATIONS_SERVICE_URL}/notifications/send",
            target_service="notifications",
            json_data={
                "recipient": payload.user_id,
                "subject": "Payment Receipt",
                "body": f"Your payment of ${payload.amount:.2f} was successfully processed.",
            },
            client=notif_client,
        )
    except Exception as exc:
        logger.warning(
            f"Failed to dispatch payment notification: {exc}",
            attributes={"error": str(exc)},
        )

    return record


@app.get("/payments/{payment_id}")
async def get_payment(payment_id: str):
    """Retrieve transaction record by ID."""
    failure_injector.inject_failure_if_needed("get_payment")
    record = TRANSACTIONS.get(payment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return record
