"""Orders microservice managing order lifecycle and inventory reservation."""
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

SERVICE_NAME = "orders"

logger = get_service_logger(SERVICE_NAME)
http_client = ServiceHttpClient(caller_service=SERVICE_NAME)

INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8004")
NOTIFICATIONS_SERVICE_URL = os.getenv("NOTIFICATIONS_SERVICE_URL", "http://notifications:8005")

# In-memory order datastore
ORDERS: dict[str, dict[str, Any]] = {}

# Customer tier bonus multipliers for loyalty program
CUSTOMER_TIERS = {
    "STANDARD": 1.0,
    "VIP": 1.5,
    "GOLD": 2.0,
}

# Test override client hook for ASGITransport testing
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


class OrderItem(BaseModel):
    sku: str
    quantity: int = 1
    unit_price: float = Field(default=25.0)


class CreateOrderRequest(BaseModel):
    user_id: str
    items: list[OrderItem] = Field(..., min_length=1, description="List of items with sku and quantity")
    total_amount: float = Field(..., ge=0)
    currency: str = "USD"


@app.get("/health")
async def health():
    """Service healthcheck."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/orders")
async def create_order(payload: CreateOrderRequest):
    """Place a new order, reserve inventory, and send confirmation."""
    order_id = f"ord-{uuid.uuid4().hex[:8]}"

    # Loyalty tier
    parts = payload.user_id.split("-")
    if len(parts) >= 4 and parts[0] == "user" and parts[1] == "tier":
        user_tier = parts[2].upper()
        tier_multiplier = CUSTOMER_TIERS[user_tier]
    else:
        tier_multiplier = 1.0

    loyalty_points = int(payload.total_amount * tier_multiplier)

    # 1. Call Inventory service to reserve items
    inv_client = target_service_clients.get("inventory")
    inv_items = [{"sku": i.sku, "quantity": i.quantity} for i in payload.items]
    inv_resp = await http_client.post(
        url=f"{INVENTORY_SERVICE_URL}/inventory/reserve",
        target_service="inventory",
        json_data={"items": inv_items},
        client=inv_client,
    )

    if inv_resp.status_code != 200:
        err_code = inv_resp.headers.get("x-error-code", f"HTTP_{inv_resp.status_code}")
        logger.error(
            f"Failed to reserve inventory for order {order_id}: {inv_resp.text} [{err_code}]",
            event_type="downstream_call_failed",
            error_code=err_code,
            downstream_service="inventory",
            attributes={
                "order_id": order_id,
                "status_code": inv_resp.status_code,
                "downstream_service": "inventory",
                "error_code": err_code,
                "response": inv_resp.text[:200],
            },
        )
        return JSONResponse(
            status_code=inv_resp.status_code,
            content=inv_resp.json() if inv_resp.headers.get("content-type", "").startswith("application/json") else {"detail": inv_resp.text},
            headers={"x-error-code": err_code},
        )

    # 2. Persist order record
    order_record = {
        "order_id": order_id,
        "user_id": payload.user_id,
        "items": [item.model_dump() for item in payload.items],
        "total_amount": payload.total_amount,
        "currency": payload.currency,
        "loyalty_points": loyalty_points,
        "status": "CONFIRMED",
    }
    ORDERS[order_id] = order_record

    logger.info(
        f"Order {order_id} created successfully for user {payload.user_id} (pts={loyalty_points})",
        event_type="order_created",
        attributes={"order_id": order_id, "amount": payload.total_amount, "loyalty_points": loyalty_points},
    )

    # 3. Call Notifications service (best-effort fire-and-forget alert)
    notif_client = target_service_clients.get("notifications")
    try:
        await http_client.post(
            url=f"{NOTIFICATIONS_SERVICE_URL}/notifications/send",
            target_service="notifications",
            json_data={
                "recipient": payload.user_id,
                "subject": "Order Confirmation",
                "body": f"Your order {order_id} for ${payload.total_amount:.2f} is confirmed.",
                "channel": "email",
                "order_id": order_id,
            },
            client=notif_client,
        )
    except Exception as exc:
        logger.warning(
            f"Failed to dispatch order notification: {exc}",
            event_type="notification_failed",
            attributes={"order_id": order_id, "error": str(exc)},
        )

    return order_record


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    """Retrieve order details by ID."""
    record = ORDERS.get(order_id)
    if not record:
        logger.warning(
            f"Order {order_id} not found",
            event_type="order_not_found",
            error_code="ORDER_NOT_FOUND",
            attributes={"order_id": order_id},
        )
        raise HTTPException(
            status_code=404,
            detail=f"Order '{order_id}' not found",
            headers={"x-error-code": "ORDER_NOT_FOUND"},
        )
    return record
