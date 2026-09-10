"""Execution Memory layer backed by Redis for active investigation checkpointing."""
import json
from typing import Any, Dict, List, Optional, Set

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.redis.client import get_redis_client

logger = get_logger(__name__)


class ExecutionMemory:
    """Manages ephemeral working state, visited files/symbols, and LangGraph checkpoints in Redis."""

    def __init__(self, ttl_seconds: Optional[int] = None) -> None:
        self.ttl = ttl_seconds or settings.STAGE4_EXECUTION_MEMORY_TTL_SECONDS

    @staticmethod
    def _key(incident_id: str) -> str:
        return f"incident:agent:exec:{incident_id}"

    async def save_checkpoint(self, incident_id: str, state: Dict[str, Any]) -> None:
        """Persist current LangGraph state snapshot into Redis with TTL."""
        client = await get_redis_client()
        key = self._key(incident_id)
        try:
            serialized = json.dumps(state, default=str)
            await client.set(key, serialized, ex=self.ttl)
        except Exception as exc:
            logger.warning("Failed saving execution memory checkpoint for %s: %s", incident_id, exc)

    async def load_checkpoint(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Load the latest investigation checkpoint from Redis."""
        client = await get_redis_client()
        key = self._key(incident_id)
        try:
            val = await client.get(key)
            if not val:
                return None
            return json.loads(val)
        except Exception as exc:
            logger.warning("Failed loading execution memory checkpoint for %s: %s", incident_id, exc)
            return None

    async def add_visited(self, incident_id: str, category: str, item: str) -> None:
        """Record a visited file, symbol, or document to prevent duplicate exploration."""
        client = await get_redis_client()
        key = f"incident:agent:visited:{category}:{incident_id}"
        try:
            await client.sadd(key, item)
            await client.expire(key, self.ttl)
        except Exception as exc:
            logger.warning("Failed recording visited %s in execution memory: %s", category, exc)

    async def get_visited(self, incident_id: str, category: str) -> Set[str]:
        """Retrieve set of already visited items for a category."""
        client = await get_redis_client()
        key = f"incident:agent:visited:{category}:{incident_id}"
        try:
            members = await client.smembers(key)
            return {m.decode("utf-8") if isinstance(m, bytes) else str(m) for m in members}
        except Exception as exc:
            logger.warning("Failed reading visited %s from execution memory: %s", category, exc)
            return set()

    async def clear(self, incident_id: str) -> None:
        """Purge execution memory for a resolved or aborted investigation."""
        client = await get_redis_client()
        try:
            keys = [
                self._key(incident_id),
                f"incident:agent:visited:files:{incident_id}",
                f"incident:agent:visited:symbols:{incident_id}",
                f"incident:agent:visited:docs:{incident_id}",
            ]
            await client.delete(*keys)
        except Exception as exc:
            logger.warning("Failed clearing execution memory for %s: %s", incident_id, exc)


# Global singleton instance
execution_memory = ExecutionMemory()
