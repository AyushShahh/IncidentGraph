"""Redis index for high-speed active incident fingerprint lookups."""
import uuid
from typing import List, Optional, Dict
from backend.redis.client import get_redis_client
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

KEY_PREFIX = "incident:fp:"


class RedisFingerprintIndex:
    """Manages ephemeral fingerprint-to-incident_id mappings in Redis.

    Only active incident fingerprints are indexed to achieve O(1) duplicate checks.
    Full incident objects are never stored in Redis.
    """

    def __init__(self, key_prefix: str = KEY_PREFIX):
        self.prefix = key_prefix

    def _key(self, fingerprint: str) -> str:
        return f"{self.prefix}{fingerprint}"

    async def lookup_fingerprint(self, fingerprint: str) -> Optional[str]:
        """Check if a fingerprint is currently mapped to an active incident."""
        redis = await get_redis_client()
        return await redis.get(self._key(fingerprint))

    async def lookup_fingerprints_batch(
        self,
        fingerprints: List[str],
    ) -> Dict[str, Optional[str]]:
        """Batch lookup fingerprints using Redis MGET.

        Returns:
            Dictionary mapping each fingerprint to its active incident_id or None.
        """
        if not fingerprints:
            return {}

        redis = await get_redis_client()
        keys = [self._key(fp) for fp in fingerprints]
        values = await redis.mget(keys)

        return {fp: val for fp, val in zip(fingerprints, values)}

    async def index_fingerprint(
        self,
        fingerprint: str,
        incident_id: uuid.UUID | str,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store active fingerprint mapping with TTL."""
        redis = await get_redis_client()
        ttl = ttl_seconds or settings.REDIS_FINGERPRINT_TTL_SECONDS
        key = self._key(fingerprint)
        await redis.set(key, str(incident_id), ex=ttl)

    async def index_fingerprints_batch(
        self,
        mappings: Dict[str, uuid.UUID | str],
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Batch index multiple fingerprint-to-incident mappings using pipeline."""
        if not mappings:
            return

        redis = await get_redis_client()
        ttl = ttl_seconds or settings.REDIS_FINGERPRINT_TTL_SECONDS

        async with redis.pipeline(transaction=False) as pipe:
            for fp, inc_id in mappings.items():
                pipe.set(self._key(fp), str(inc_id), ex=ttl)
            await pipe.execute()

    async def delete_fingerprints(self, fingerprints: List[str]) -> None:
        """Remove fingerprint mappings when an incident is resolved."""
        if not fingerprints:
            return

        redis = await get_redis_client()
        keys = [self._key(fp) for fp in fingerprints]
        await redis.delete(*keys)

    async def clear_all_fingerprints(self) -> None:
        """Clear all active incident fingerprint keys from Redis (for tests/resets)."""
        redis = await get_redis_client()
        keys = await redis.keys(f"{self.prefix}*")
        if keys:
            await redis.delete(*keys)


redis_index = RedisFingerprintIndex()
