"""Asynchronous Redis client connection manager."""
import asyncio
import redis.asyncio as aioredis
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_redis_client: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


async def get_redis_client() -> aioredis.Redis:
    """Provides an async Redis client instance matching the current event loop."""
    global _redis_client, _redis_loop
    current_loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_loop != current_loop:
        logger.info("Initializing async Redis client connection...")
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        _redis_loop = current_loop
    return _redis_client


async def close_redis_client() -> None:
    """Gracefully closes the async Redis connection pool."""
    global _redis_client, _redis_loop
    if _redis_client:
        logger.info("Closing async Redis client connection...")
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None
        _redis_loop = None
