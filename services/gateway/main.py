"""API Gateway service orchestrating downstream microservices."""
from contextlib import asynccontextmanager
import os
from typing import Any, AsyncGenerator, Optional
from fastapi import FastAPI, HTTPException, Request, Response
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

SERVICE_NAME = "gateway"

logger = get_service_logger(SERVICE_NAME)
failure_injector = get_shared_failure_injector(SERVICE_NAME)
http_client = ServiceHttpClient(caller_service=SERVICE_NAME)

ORDERS_SERVICE_URL = os.getenv("ORDERS_SERVICE_URL", "http://orders:8002")
PAYMENTS_SERVICE_URL = os.getenv("PAYMENTS_SERVICE_URL", "http://payments:8003")

# Test override client hook for ASGITransport testing
target_service_clients: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    producer = get_shared_kafka_producer()
    try:
        await producer.start()
        logger.info("Gateway service initialized and connected to Kafka.")
    except Exception as exc:
        logger.warning("Kafka producer connection deferred or failed: %s", exc)

    yield

    await http_client.close()
    await producer.stop()
    logger.info("Gateway service shut down cleanly.")


app = FastAPI(title="API Gateway Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(TraceCorrelationMiddleware, service_name=SERVICE_NAME)


# Custom exception handlers for simulated faults
@app.exception_handler(DatabaseTimeoutException)
async def db_timeout_handler(request: Request, exc: DatabaseTimeoutException):
    return JSONResponse(status_code=504, content={"detail": str(exc), "error": "database_timeout"})


@app.exception_handler(NetworkTimeoutException)
async def net_timeout_handler(request: Request, exc: NetworkTimeoutException):
    return JSONResponse(status_code=504, content={"detail": str(exc), "error": "network_timeout"})


@app.exception_handler(RetryExhaustionException)
async def retry_exhaust_handler(request: Request, exc: RetryExhaustionException):
    return JSONResponse(status_code=503, content={"detail": str(exc), "error": "retry_exhaustion"})


class CheckoutItem(BaseModel):
    sku: str
    quantity: int = 1
    unit_price: float = Field(..., gt=0)


class CheckoutRequest(BaseModel):
    user_id: str
    items: list[CheckoutItem]
    payment_method: str = "credit_card"


@app.get("/health")
async def health():
    """Service healthcheck."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/api/status")
@app.get("/status")
async def system_status():
    """Returns gateway configuration and failure injection settings."""
    return {
        "service": SERVICE_NAME,
        "failure_rate": failure_injector.failure_rate,
        "enabled_failures": failure_injector.enabled_failures,
        "calls_recorded": failure_injector.call_count,
    }


@app.post("/simulate-failure")
@app.post("/api/simulate-failure")
async def configure_failure_simulation(payload: FailureConfigRequest):
    """Dynamically configure failure injector for gateway or a specific service."""
    target = payload.target_service or SERVICE_NAME
    injector = get_shared_failure_injector(target)
    injector.configure(
        failure_rate=payload.failure_rate,
        enabled_failures=payload.enabled_failures,
        trigger_after_n_calls=payload.trigger_after_n_calls,
    )
    logger.info(
        f"Updated failure configuration for service '{target}' (rate={injector.failure_rate})",
        event_type="failure_config_updated",
        attributes={"service": target, "rate": injector.failure_rate},
    )
    return {
        "status": "updated",
        "target_service": target,
        "failure_rate": injector.failure_rate,
        "enabled_failures": injector.enabled_failures,
        "trigger_after_n_calls": injector.trigger_after_n_calls,
    }


@app.post("/api/checkout")
async def checkout(payload: CheckoutRequest):
    """End-to-end checkout coordinating orders, inventory, payments, and notifications."""
    failure_injector.inject_failure_if_needed("checkout")

    total_amount = sum(item.quantity * item.unit_price for item in payload.items)
    order_items = [{"sku": i.sku, "quantity": i.quantity} for i in payload.items]

    # 1. Dispatch order creation to Orders service
    orders_client = target_service_clients.get("orders")
    order_resp = await http_client.post(
        url=f"{ORDERS_SERVICE_URL}/orders",
        target_service="orders",
        json_data={
            "user_id": payload.user_id,
            "items": order_items,
            "total_amount": total_amount,
        },
        client=orders_client,
    )

    if order_resp.status_code != 200:
        logger.error(
            f"Checkout aborted: Orders service returned {order_resp.status_code}",
            event_type="error",
            attributes={"status_code": order_resp.status_code, "response": order_resp.text},
        )
        raise HTTPException(
            status_code=order_resp.status_code,
            detail=f"Order creation failed: {order_resp.text}",
        )

    order_data = order_resp.json()
    order_id = order_data["order_id"]

    # 2. Dispatch payment processing to Payments service
    payments_client = target_service_clients.get("payments")
    payment_resp = await http_client.post(
        url=f"{PAYMENTS_SERVICE_URL}/payments/charge",
        target_service="payments",
        json_data={
            "user_id": payload.user_id,
            "amount": total_amount,
            "currency": "USD",
            "order_id": order_id,
        },
        client=payments_client,
    )

    if payment_resp.status_code != 200:
        logger.error(
            f"Checkout aborted: Payments service returned {payment_resp.status_code}",
            event_type="error",
            attributes={"order_id": order_id, "status_code": payment_resp.status_code},
        )
        raise HTTPException(
            status_code=payment_resp.status_code,
            detail=f"Payment processing failed: {payment_resp.text}",
        )

    payment_data = payment_resp.json()

    logger.info(
        f"Checkout successfully completed for user {payload.user_id}, order {order_id}",
        event_type="checkout_completed",
        attributes={"order_id": order_id, "total_amount": total_amount},
    )

    return {
        "status": "COMPLETED",
        "order": order_data,
        "payment": payment_data,
    }
