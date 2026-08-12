"""Hot feature store backed by Redis.

Keeps only the latest snapshot per match — that's all the online
inference path needs. Cold history is accessed through Anvil;
those reads happen during training, not in the hot path.
"""

from __future__ import annotations

import logging
from uuid import UUID

import orjson
from redis.asyncio import Redis

from atlas.features.snapshot import FeatureSnapshot

logger = logging.getLogger(__name__)


class FeatureStore:
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

    def _key(self, match_id: UUID) -> str:
        return f"{self._prefix}{match_id}"

    async def put(self, snapshot: FeatureSnapshot) -> None:
        payload = orjson.dumps(snapshot.to_json_dict())
        try:
            await self._r.set(self._key(snapshot.match_id), payload, ex=self._ttl)
        except Exception:
            logger.exception(
                "feature_store_put_failed",
                extra={"match_id": str(snapshot.match_id)},
            )
            raise

    async def get(self, match_id: UUID) -> FeatureSnapshot | None:
        try:
            raw = await self._r.get(self._key(match_id))
        except Exception:
            logger.exception(
                "feature_store_get_failed", extra={"match_id": str(match_id)}
            )
            return None
        if raw is None:
            return None
        try:
            data = orjson.loads(raw)
            return FeatureSnapshot.model_validate(data)
        except Exception:
            logger.exception(
                "feature_store_decode_failed", extra={"match_id": str(match_id)}
            )
            return None
