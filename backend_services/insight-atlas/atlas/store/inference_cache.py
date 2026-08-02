"""Short-TTL cache for inference output, keyed by (match_id, schema_version).

The hot path consults this before running any models — multiple
concurrent calls for the same match within a few seconds collapse onto
one inference.
"""

from __future__ import annotations

import logging
from uuid import UUID

import orjson
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class InferenceCache:
    def __init__(
        self,
        *,
        redis: Redis,
        key_prefix: str,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._r = redis
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, match_id: UUID, schema_version: int) -> str:
        return f"{self._prefix}{match_id}:v{schema_version}"

    async def get(self, match_id: UUID, schema_version: int) -> dict | None:
        try:
            raw = await self._r.get(self._key(match_id, schema_version))
        except Exception:
            logger.exception(
                "inference_cache_get_failed", extra={"match_id": str(match_id)}
            )
            return None
        if raw is None:
            return None
        try:
            return orjson.loads(raw)
        except Exception:
            return None

    async def put(self, match_id: UUID, schema_version: int, payload: dict) -> None:
        try:
            await self._r.set(
                self._key(match_id, schema_version),
                orjson.dumps(payload),
                ex=self._ttl,
            )
        except Exception:
            logger.exception(
                "inference_cache_put_failed", extra={"match_id": str(match_id)}
            )
            raise
