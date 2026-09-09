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
from shared.http_client import ServiceHttpClient

SERVICE_NAME = "gateway"

logger = get_service_logger(SERVICE_NAME)
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


class CheckoutItem(BaseModel):
    sku: str
    quantity: int = 1
    unit_price: float = Field(default=25.0)


class CheckoutRequest(BaseModel):
    user_id: str
    items: list[CheckoutItem]
    payment_method: str = "credit_card"
    currency: str = "USD"
    discount_code: Optional[str] = None


def check_service_health() -> bool:
    """Internal service health probe."""
    return True


@app.get("/health")
async def health():
    """Service healthcheck."""
    check_service_health()
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/api/checkout")
async def checkout(payload: CheckoutRequest):
    """End-to-end checkout coordinating orders, inventory, payments, and notifications."""
    if not payload.user_id:
        raise HTTPException(
            status_code=400,
            detail="user_id is required for checkout",
            headers={"x-error-code": "INVALID_USER_ID"},
        )

    if not payload.items:
        raise HTTPException(
            status_code=400,
            detail="Order items list cannot be empty",
            headers={"x-error-code": "EMPTY_ITEMS_LIST"},
        )

    # Calculate pricing
    gross_amount = sum(item.quantity * item.unit_price for item in payload.items)

    # Discount thing
    if payload.discount_code:
        discount_amount = 10.0 if payload.discount_code == "SAVE10" else 0.0
        if payload.discount_code == "ZERO_SUBTOTAL":
            discount_amount = gross_amount
        # BUG: missing check for gross_amount > 0
        discount_ratio = discount_amount / gross_amount

    total_amount = max(0.0, round(gross_amount, 2))
    order_items = [{"sku": i.sku, "quantity": i.quantity, "unit_price": i.unit_price} for i in payload.items]

    # 1. Dispatch order creation to Orders service
    orders_client = target_service_clients.get("orders")
    order_resp = await http_client.post(
        url=f"{ORDERS_SERVICE_URL}/orders",
        target_service="orders",
        json_data={
            "user_id": payload.user_id,
            "items": order_items,
            "total_amount": total_amount,
            "currency": payload.currency,
        },
        client=orders_client,
    )

    if order_resp.status_code != 200:
        err_code = order_resp.headers.get("x-error-code", f"HTTP_{order_resp.status_code}")
        logger.error(
            f"Checkout aborted: Orders service returned status {order_resp.status_code} [{err_code}]",
            event_type="downstream_call_failed",
            error_code=err_code,
            downstream_service="orders",
            attributes={
                "status_code": order_resp.status_code,
                "downstream_service": "orders",
                "error_code": err_code,
                "response": order_resp.text[:200],
            },
        )
        return JSONResponse(
            status_code=order_resp.status_code,
            content=order_resp.json() if order_resp.headers.get("content-type", "").startswith("application/json") else {"detail": order_resp.text},
            headers={"x-error-code": err_code},
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
            "currency": payload.currency,
            "order_id": order_id,
            "payment_method": payload.payment_method,
        },
        client=payments_client,
    )

    if payment_resp.status_code != 200:
        err_code = payment_resp.headers.get("x-error-code", f"HTTP_{payment_resp.status_code}")
        logger.error(
            f"Checkout aborted: Payments service returned status {payment_resp.status_code} [{err_code}]",
            event_type="downstream_call_failed",
            error_code=err_code,
            downstream_service="payments",
            attributes={
                "order_id": order_id,
                "status_code": payment_resp.status_code,
                "downstream_service": "payments",
                "error_code": err_code,
                "response": payment_resp.text[:200],
            },
        )
        return JSONResponse(
            status_code=payment_resp.status_code,
            content=payment_resp.json() if payment_resp.headers.get("content-type", "").startswith("application/json") else {"detail": payment_resp.text},
            headers={"x-error-code": err_code},
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


@app.get("/api/orders/{order_id}")
async def get_order_proxy(order_id: str):
    """Proxy request to retrieve order details from Orders service."""
    orders_client = target_service_clients.get("orders")
    resp = await http_client.get(
        url=f"{ORDERS_SERVICE_URL}/orders/{order_id}",
        target_service="orders",
        client=orders_client,
    )
    return JSONResponse(
        status_code=resp.status_code,
        content=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"detail": resp.text},
        headers={"x-error-code": resp.headers.get("x-error-code", "")},
    )
