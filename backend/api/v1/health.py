"""Healthcheck and dependency readiness probes for the platform backend."""
import logging
from typing import Any
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from aiokafka import AIOKafkaProducer

from backend.core.config import settings
from backend.db.session import engine
from backend.redis.client import get_redis_client
from backend.qdrant.client import get_qdrant_client

logger = logging.getLogger("backend.health")
router = APIRouter()


@router.get("", summary="Liveness check")
@router.get("/", summary="Liveness check", include_in_schema=False)
async def health_check() -> dict[str, Any]:
    """Returns platform liveness status and version metadata."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
    }


@router.get("/ready", summary="Readiness probe")
@router.get("/ready/", summary="Readiness probe", include_in_schema=False)
async def readiness_check() -> dict[str, Any]:
    """Verify active connectivity to Postgres, Redis, Kafka, and Qdrant."""
    readiness_status: dict[str, str] = {
        "postgres": "unknown",
        "redis": "unknown",
        "kafka": "unknown",
        "qdrant": "unknown",
    }
    errors: list[str] = []

    # 1. Check PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        readiness_status["postgres"] = "ready"
    except Exception as exc:
        readiness_status["postgres"] = f"unhealthy: {exc}"
        errors.append(f"PostgreSQL: {exc}")

    # 2. Check Redis
    try:
        redis_client = await get_redis_client()
        pong = await redis_client.ping()
        if pong:
            readiness_status["redis"] = "ready"
        else:
            readiness_status["redis"] = "unhealthy: no ping response"
            errors.append("Redis: no ping response")
    except Exception as exc:
        readiness_status["redis"] = f"unhealthy: {exc}"
        errors.append(f"Redis: {exc}")

    # 3. Check Kafka
    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            request_timeout_ms=3000,
        )
        await producer.start()
        await producer.stop()
        readiness_status["kafka"] = "ready"
    except Exception as exc:
        readiness_status["kafka"] = f"unhealthy: {exc}"
        errors.append(f"Kafka: {exc}")

    # 4. Check Qdrant
    try:
        qdrant_client = await get_qdrant_client()
        await qdrant_client.get_collections()
        readiness_status["qdrant"] = "ready"
    except Exception as exc:
        readiness_status["qdrant"] = f"unhealthy: {exc}"
        errors.append(f"Qdrant: {exc}")

    if errors:
        logger.error("Readiness check failed: %s", errors)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "checks": readiness_status, "errors": errors},
        )

    return {
        "status": "ready",
        "service": settings.PROJECT_NAME,
        "checks": readiness_status,
    }
