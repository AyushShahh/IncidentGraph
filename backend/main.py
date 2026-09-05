"""Main entry point for the AI Incident Intelligence Platform backend."""
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from aiokafka import AIOKafkaProducer

from backend.core.config import settings
from backend.core.logging import setup_logging
from backend.api.router import api_router
from backend.api.v1.health import router as health_router
from backend.db.session import engine
from backend.redis.client import get_redis_client, close_redis_client
from backend.qdrant.client import get_qdrant_client

setup_logging()
logger = logging.getLogger("backend.main")


async def verify_infrastructure_connections() -> None:
    """Verify connections to Kafka, PostgreSQL, Redis, and Qdrant at startup."""
    logger.info("Verifying infrastructure dependencies (PostgreSQL, Redis, Kafka, Qdrant)...")

    # 1. PostgreSQL
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Connected to PostgreSQL successfully.")
    except Exception as exc:
        logger.error("Failed to connect to PostgreSQL at %s: %s", settings.DATABASE_URL, exc)
        raise RuntimeError(f"PostgreSQL connection failed: {exc}") from exc

    # 2. Redis
    try:
        redis = await get_redis_client()
        await redis.ping()
        logger.info("Connected to Redis successfully.")
    except Exception as exc:
        logger.error("Failed to connect to Redis at %s: %s", settings.REDIS_URL, exc)
        raise RuntimeError(f"Redis connection failed: {exc}") from exc

    # 3. Kafka
    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            request_timeout_ms=5000,
        )
        await producer.start()
        await producer.stop()
        logger.info("Connected to Kafka broker at %s successfully.", settings.KAFKA_BOOTSTRAP_SERVERS)
    except Exception as exc:
        logger.error("Failed to connect to Kafka at %s: %s", settings.KAFKA_BOOTSTRAP_SERVERS, exc)
        raise RuntimeError(f"Kafka connection failed: {exc}") from exc

    # 4. Qdrant
    try:
        qdrant = await get_qdrant_client()
        await qdrant.get_collections()
        logger.info("Connected to Qdrant at %s:%s successfully.", settings.QDRANT_HOST, settings.QDRANT_HTTP_PORT)
    except Exception as exc:
        logger.error("Failed to connect to Qdrant at %s:%s: %s", settings.QDRANT_HOST, settings.QDRANT_HTTP_PORT, exc)
        raise RuntimeError(f"Qdrant connection failed: {exc}") from exc

    logger.info("All infrastructure dependencies verified successfully.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    logger.info("Initializing %s v%s...", settings.PROJECT_NAME, settings.VERSION)

    # Fail fast if dependencies are unavailable
    await verify_infrastructure_connections()

    yield

    logger.info("Shutting down %s...", settings.PROJECT_NAME)
    await close_redis_client()
    await engine.dispose()
    logger.info("Platform backend stopped.")


def create_application() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include root API router
    app.include_router(api_router, prefix=settings.API_V1_STR)
    app.include_router(health_router, prefix="/health", tags=["Health"])

    @app.get("/", tags=["Root"])
    async def root_redirect():
        return {
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "status": "healthy",
            "docs": f"{settings.API_V1_STR}/docs",
        }

    return app


app = create_application()
