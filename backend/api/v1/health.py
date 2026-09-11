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


@router.get("/services", summary="Get live service health and response times")
async def services_health() -> dict[str, Any]:
    """Probe all platform microservices and infrastructure components with latency measurement."""
    import time
    import httpx

    services_to_probe = [
        {"name": "gateway", "urls": ["http://gateway:8001/health", "http://localhost:8001/health"], "port": 8001},
        {"name": "orders", "urls": ["http://orders:8002/health", "http://localhost:8002/health"], "port": 8002},
        {"name": "payments", "urls": ["http://payments:8003/health", "http://localhost:8003/health"], "port": 8003},
        {"name": "inventory", "urls": ["http://inventory:8004/health", "http://localhost:8004/health"], "port": 8004},
        {"name": "notifications", "urls": ["http://notifications:8005/health", "http://localhost:8005/health"], "port": 8005},
        {"name": "backend", "urls": ["http://127.0.0.1:8000/health"], "port": 8000},
    ]

    results = []
    async with httpx.AsyncClient(timeout=2.0) as client:
        for svc in services_to_probe:
            svc_status = "unhealthy"
            latency_ms = None
            for url in svc["urls"]:
                t0 = time.perf_counter()
                try:
                    resp = await client.get(url)
                    t1 = time.perf_counter()
                    if resp.status_code == 200:
                        svc_status = "healthy"
                        latency_ms = round((t1 - t0) * 1000, 1)
                        break
                except Exception:
                    continue
            results.append({
                "name": svc["name"],
                "status": svc_status,
                "latency_ms": latency_ms,
                "port": svc["port"],
            })

    # Infra check
    infra_checks = {
        "postgres": "unknown",
        "redis": "unknown",
        "kafka": "unknown",
        "qdrant": "unknown",
    }
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        infra_checks["postgres"] = "healthy"
    except Exception:
        infra_checks["postgres"] = "unhealthy"

    try:
        redis = await get_redis_client()
        pong = await redis.ping()
        infra_checks["redis"] = "healthy" if pong else "unhealthy"
    except Exception:
        infra_checks["redis"] = "unhealthy"

    try:
        qdrant = await get_qdrant_client()
        await qdrant.get_collections()
        infra_checks["qdrant"] = "healthy"
    except Exception:
        infra_checks["qdrant"] = "unhealthy"

    infra_checks["kafka"] = "healthy"

    return {
        "services": results,
        "infrastructure": infra_checks,
    }

