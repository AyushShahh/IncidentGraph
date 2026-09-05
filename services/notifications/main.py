"""Notifications microservice for dispatching event notifications."""
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from fastapi import FastAPI, Request
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

SERVICE_NAME = "notifications"

logger = get_service_logger(SERVICE_NAME)
failure_injector = get_shared_failure_injector(SERVICE_NAME)

# In-memory history for testing
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


@app.exception_handler(DatabaseTimeoutException)
async def db_timeout_handler(request: Request, exc: DatabaseTimeoutException):
    return JSONResponse(status_code=504, content={"detail": str(exc), "error": "database_timeout"})


@app.exception_handler(NetworkTimeoutException)
async def net_timeout_handler(request: Request, exc: NetworkTimeoutException):
    return JSONResponse(status_code=504, content={"detail": str(exc), "error": "network_timeout"})


@app.exception_handler(RetryExhaustionException)
async def retry_exhaust_handler(request: Request, exc: RetryExhaustionException):
    return JSONResponse(status_code=503, content={"detail": str(exc), "error": "retry_exhaustion"})


class SendNotificationRequest(BaseModel):
    recipient: str = Field(..., description="Target email or user ID")
    channel: str = Field(default="email", description="email, sms, or webhook")
    subject: str = Field(..., description="Notification subject line")
    body: str = Field(..., description="Notification message body")


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


@app.post("/notifications/send")
async def send_notification(payload: SendNotificationRequest):
    """Dispatch simulated notification to user or channel."""
    failure_injector.inject_failure_if_needed("send_notification")

    record = payload.model_dump()
    NOTIFICATION_HISTORY.append(record)

    logger.info(
        f"Dispatched {payload.channel} alert to {payload.recipient}: {payload.subject}",
        event_type="notification_dispatched",
        attributes={"recipient": payload.recipient, "channel": payload.channel},
    )
    return {"status": "sent", "recipient": payload.recipient, "channel": payload.channel}


@app.get("/notifications/history")
async def get_history():
    """Return historical sent notifications."""
    return {"count": len(NOTIFICATION_HISTORY), "notifications": list(NOTIFICATION_HISTORY)}
