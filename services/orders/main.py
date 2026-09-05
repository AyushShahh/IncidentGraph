"""Orders microservice for order placement and coordination."""
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

SERVICE_NAME = "orders"

logger = get_service_logger(SERVICE_NAME)
failure_injector = get_shared_failure_injector(SERVICE_NAME)
http_client = ServiceHttpClient(caller_service=SERVICE_NAME)

INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8004")
NOTIFICATIONS_SERVICE_URL = os.getenv("NOTIFICATIONS_SERVICE_URL", "http://notifications:8005")

# In-memory orders database
ORDERS: dict[str, dict[str, Any]] = {}

# Test override client hook
target_service_clients: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    producer = get_shared_kafka_producer()
    try:
        await producer.start()
        logger.info("Orders service initialized and connected to Kafka.")
    except Exception as exc:
        logger.warning("Kafka producer connection deferred or failed: %s", exc)

    yield

    await http_client.close()
    await producer.stop()
    logger.info("Orders service shut down cleanly.")


app = FastAPI(title="Orders Service", version="0.1.0", lifespan=lifespan)
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


class CreateOrderRequest(BaseModel):
    user_id: str
    items: list[dict[str, Any]] = Field(..., description="List of items with sku and quantity")
    total_amount: float = Field(..., gt=0)


@app.get("/health")
async def health():
    """Service healthcheck."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/simulate-failure")
async def configure_failure(payload: FailureConfigRequest):
    """Configure failure injector settings at runtime."""
    failure_injector.configure(
        failure_rate=payload.failure_rate,
        enabled_failures=payload.enabled_failures,
        trigger_after_n_calls=payload.trigger_after_n_calls,
    )
    return {
        "status": "updated",
        "service": SERVICE_NAME,
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


@app.post("/orders")
async def create_order(payload: CreateOrderRequest):
    """Place a new order, reserve inventory, and send confirmation."""
    failure_injector.inject_failure_if_needed("create_order")

    order_id = f"ord-{uuid.uuid4().hex[:8]}"

    # 1. Call Inventory service to reserve items
    inv_client = target_service_clients.get("inventory")
    inv_resp = await http_client.post(
        url=f"{INVENTORY_SERVICE_URL}/inventory/reserve",
        target_service="inventory",
        json_data={"items": payload.items},
        client=inv_client,
    )

    if inv_resp.status_code != 200:
        logger.error(
            f"Failed to reserve inventory for order {order_id}: {inv_resp.text}",
            event_type="error",
            attributes={"status_code": inv_resp.status_code, "response": inv_resp.text},
        )
        raise HTTPException(
            status_code=inv_resp.status_code,
            detail=f"Inventory reservation failed: {inv_resp.text}",
        )

    # 2. Persist order record
    order_record = {
        "order_id": order_id,
        "user_id": payload.user_id,
        "items": payload.items,
        "total_amount": payload.total_amount,
        "status": "CONFIRMED",
    }
    ORDERS[order_id] = order_record

    logger.info(
        f"Order {order_id} created successfully for user {payload.user_id}",
        event_type="order_created",
        attributes={"order_id": order_id, "amount": payload.total_amount},
    )

    # 3. Call Notifications service
    notif_client = target_service_clients.get("notifications")
    try:
        await http_client.post(
            url=f"{NOTIFICATIONS_SERVICE_URL}/notifications/send",
            target_service="notifications",
            json_data={
                "recipient": payload.user_id,
                "subject": "Order Confirmation",
                "body": f"Your order {order_id} for ${payload.total_amount:.2f} is confirmed.",
            },
            client=notif_client,
        )
    except Exception as exc:
        logger.warning(f"Could not send order confirmation alert: {exc}")

    return order_record


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    """Retrieve order details by ID."""
    failure_injector.inject_failure_if_needed("get_order")
    record = ORDERS.get(order_id)
    if not record:
        raise HTTPException(status_code=404, detail="Order not found")
    return record
