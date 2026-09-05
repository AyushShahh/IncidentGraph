"""Inventory microservice tracking SKU availability and reservations."""
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.logging.middleware import TraceCorrelationMiddleware
from shared.logging.logger import get_service_logger
from shared.kafka.producer import get_shared_kafka_producer

SERVICE_NAME = "inventory"

logger = get_service_logger(SERVICE_NAME)

# In-memory stock catalog
DEFAULT_STOCK = {
    "SKU-100": 100,  # High stock standard catalog item
    "SKU-200": 50,   # Moderate stock catalog item
    "SKU-LIMITED": 2, # Limited stock item - naturally runs out of stock under load
    "SKU-OUT-OF-STOCK": 0, # Permanently depleted item
}

STOCK_STORE: dict[str, int] = dict(DEFAULT_STOCK)


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


class ReserveItemRequest(BaseModel):
    items: list[dict[str, Any]] = Field(..., description="List of items with sku and quantity")


@app.get("/health")
async def health():
    """Service healthcheck."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/inventory/{sku}")
async def get_stock(sku: str):
    """Retrieve current stock count for SKU."""
    stock = STOCK_STORE.get(sku)
    if stock is None:
        logger.warning(
            f"SKU '{sku}' not found in catalog",
            event_type="catalog_miss",
            error_code="SKU_NOT_FOUND",
            attributes={"sku": sku},
        )
        raise HTTPException(
            status_code=404,
            detail=f"SKU '{sku}' not found",
            headers={"x-error-code": "SKU_NOT_FOUND"},
        )

    logger.info(
        f"Retrieved stock for SKU '{sku}': {stock}",
        event_type="stock_checked",
        attributes={"sku": sku, "stock": stock},
    )
    return {"sku": sku, "quantity": stock}


@app.post("/inventory/reserve")
async def reserve_stock(payload: ReserveItemRequest):
    """Reserve inventory stock for ordered items."""
    # Validate payload
    if not payload.items:
        raise HTTPException(
            status_code=400,
            detail="Reservation items list cannot be empty",
            headers={"x-error-code": "EMPTY_ITEMS_LIST"},
        )

    # Logic Bug / Edge Case: Batch warehouse slicing off-by-one error
    # When reserving a multi-item order (more than 3 items), the developer implemented
    # warehouse chunking in batches of 2 items.
    # An off-by-one bug in the range boundary causes an IndexError on the final loop iteration.
    if len(payload.items) > 3:
        batch_size = 2
        batches = [payload.items[i:i + batch_size] for i in range(0, len(payload.items), batch_size)]
        # BUG: range(len(batches) + 1) instead of range(len(batches))
        for batch_idx in range(len(batches) + 1):
            _batch_chunk = batches[batch_idx]

    # Check availability and deduct
    for item in payload.items:
        sku = item.get("sku")
        qty = item.get("quantity", 1)

        if qty <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid quantity {qty} for SKU '{sku}': must be positive",
                headers={"x-error-code": "INVALID_QUANTITY"},
            )

        if sku not in STOCK_STORE:
            logger.warning(
                f"Cannot reserve SKU '{sku}': not found in product catalog",
                event_type="stock_reservation_failed",
                error_code="SKU_NOT_FOUND",
                attributes={"sku": sku, "requested": qty},
            )
            raise HTTPException(
                status_code=404,
                detail=f"SKU '{sku}' not found in catalog",
                headers={"x-error-code": "SKU_NOT_FOUND"},
            )

        available = STOCK_STORE[sku]
        if available < qty:
            logger.warning(
                f"Insufficient stock for SKU '{sku}': requested {qty}, available {available}",
                event_type="stock_reservation_failed",
                error_code="OUT_OF_STOCK",
                attributes={"sku": sku, "requested": qty, "available": available},
            )
            raise HTTPException(
                status_code=409,
                detail=f"SKU '{sku}' is out of stock (available: {available}, requested: {qty})",
                headers={"x-error-code": "OUT_OF_STOCK"},
            )

        STOCK_STORE[sku] -= qty

    logger.info(
        f"Successfully reserved stock for {len(payload.items)} item(s)",
        event_type="stock_reserved",
        attributes={"items": payload.items},
    )
    return {"status": "reserved", "items": payload.items}
