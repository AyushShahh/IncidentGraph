"""Inventory microservice for managing and reserving product stock."""
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
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

SERVICE_NAME = "inventory"

logger = get_service_logger(SERVICE_NAME)
failure_injector = get_shared_failure_injector(SERVICE_NAME)

# In-memory inventory stock
STOCK_STORE: dict[str, int] = {
    "SKU-100": 1000,
    "SKU-200": 500,
    "SKU-300": 0,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    producer = get_shared_kafka_producer()
    try:
        await producer.start()
        logger.info("Inventory service initialized and connected to Kafka.")
    except Exception as exc:
        logger.warning("Kafka producer connection deferred or failed: %s", exc)

    yield

    await producer.stop()
    logger.info("Inventory service shut down cleanly.")


app = FastAPI(title="Inventory Service", version="0.1.0", lifespan=lifespan)
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


class ReserveItemRequest(BaseModel):
    items: list[dict[str, Any]] = Field(..., description="List of items with sku and quantity")


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


@app.get("/inventory/{sku}")
async def get_stock(sku: str):
    """Retrieve current stock count for SKU."""
    failure_injector.inject_failure_if_needed("get_stock")

    stock = STOCK_STORE.get(sku)
    if stock is None:
        logger.warning(f"SKU '{sku}' not found in catalog", attributes={"sku": sku})
        raise HTTPException(status_code=404, detail=f"SKU {sku} not found")

    logger.info(f"Retrieved stock for SKU '{sku}': {stock}", attributes={"sku": sku, "stock": stock})
    return {"sku": sku, "quantity": stock}


@app.post("/inventory/reserve")
async def reserve_stock(payload: ReserveItemRequest):
    """Reserve inventory stock for ordered items."""
    failure_injector.inject_failure_if_needed("reserve_stock")

    for item in payload.items:
        sku = item.get("sku")
        qty = item.get("quantity", 1)
        available = STOCK_STORE.get(sku, 0)

        if available < qty:
            logger.error(
                f"Insufficient stock for SKU '{sku}': requested {qty}, available {available}",
                attributes={"sku": sku, "requested": qty, "available": available},
            )
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient inventory for SKU {sku}",
            )

        STOCK_STORE[sku] -= qty

    logger.info(
        f"Successfully reserved stock for {len(payload.items)} item(s)",
        event_type="db_query",
        attributes={"items": payload.items},
    )
    return {"status": "reserved", "reserved_items": payload.items}
