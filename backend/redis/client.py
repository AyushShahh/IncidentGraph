"""Asynchronous Redis client connection manager."""
import redis.asyncio as aioredis
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_redis_client: aioredis.Redis | None = None


async def get_redis_client() -> aioredis.Redis:
    """Provides a singleton async Redis client instance."""
    global _redis_client
    if _redis_client is None:
        logger.info("Initializing async Redis client connection...")
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    # TODO: Add health-check ping and reconnection handling
    return _redis_client


async def close_redis_client() -> None:
    """Gracefully closes the async Redis connection pool."""
    global _redis_client
    if _redis_client:
        logger.info("Closing async Redis client connection...")
        await _redis_client.aclose()
        _redis_client = None
