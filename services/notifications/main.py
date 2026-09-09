"""Notifications microservice dispatching email, SMS, and webhook alerts."""
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from shared.logging.middleware import TraceCorrelationMiddleware
from shared.logging.logger import get_service_logger
from shared.kafka.producer import get_shared_kafka_producer

SERVICE_NAME = "notifications"

logger = get_service_logger(SERVICE_NAME)

NOTIFICATION_HISTORY: list[dict[str, Any]] = []


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    producer = get_shared_kafka_producer()
    try:
        await producer.start()
        logger.info("Notifications service initialized and connected to Kafka.")
    except Exception as exc:
        logger.warning("Kafka producer connection deferred or failed: %s", exc)

    yield

    await producer.stop()
    logger.info("Notifications service shut down cleanly.")


app = FastAPI(title="Notifications Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(TraceCorrelationMiddleware, service_name=SERVICE_NAME)


class SendNotificationRequest(BaseModel):
    recipient: str
    subject: str
    body: str
    channel: str = Field(default="email", description="Channel: email, sms, webhook")
    order_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
async def health():
    """Service healthcheck."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/notifications/send")
async def send_notification(payload: SendNotificationRequest):
    """Dispatch simulated notification to user or channel."""
    if not payload.recipient:
        raise HTTPException(
            status_code=400,
            detail="Recipient cannot be empty",
            headers={"x-error-code": "INVALID_RECIPIENT"},
        )

    # sms
    if payload.channel == "sms":
        phone = payload.metadata["phone_number"]
        dispatch_target = phone
    else:
        dispatch_target = payload.recipient

    record = payload.model_dump()
    record["target"] = dispatch_target
    NOTIFICATION_HISTORY.append(record)

    logger.info(
        f"Dispatched {payload.channel} alert to {dispatch_target}: {payload.subject}",
        event_type="notification_dispatched",
        attributes={"recipient": payload.recipient, "channel": payload.channel, "target": dispatch_target},
    )
    return {"status": "sent", "recipient": payload.recipient, "channel": payload.channel}


@app.get("/notifications/history")
async def get_history():
    """Return historical sent notifications."""
    return {
        "count": len(NOTIFICATION_HISTORY),
        "notifications": NOTIFICATION_HISTORY[-50:],
    }
