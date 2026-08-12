"""Recalculated match-context hot store.

Holds the latest recomputed descriptive context per canonical match so
the next recalculation can carry momentum/pressure forward and so other
services can read the current contextual state. Redis-backed in
production; in-memory for tests / single instance.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import UUID

import orjson
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class MatchContextStore(Protocol):
    async def put(self, canonical_match_id: UUID, context: dict[str, Any]) -> None: ...
    async def get(self, canonical_match_id: UUID) -> dict[str, Any] | None: ...


class InMemoryMatchContextStore:
    def __init__(self) -> None:
        self._data: dict[UUID, dict[str, Any]] = {}

    async def put(self, canonical_match_id: UUID, context: dict[str, Any]) -> None:
        self._data[canonical_match_id] = dict(context)

    async def get(self, canonical_match_id: UUID) -> dict[str, Any] | None:
        value = self._data.get(canonical_match_id)
        return dict(value) if value is not None else None


class RedisMatchContextStore:
    def __init__(
        self, *, redis: Redis, key_prefix: str = "atlas:matchctx:", ttl_seconds: int = 86_400
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._r = redis
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, canonical_match_id: UUID) -> str:
        return f"{self._prefix}{canonical_match_id}"

    async def put(self, canonical_match_id: UUID, context: dict[str, Any]) -> None:
        try:
            await self._r.set(self._key(canonical_match_id), orjson.dumps(context), ex=self._ttl)
        except Exception:
            logger.exception(
                "match_context_put_failed",
                extra={"canonical_match_id": str(canonical_match_id)},
            )
            raise

    async def get(self, canonical_match_id: UUID) -> dict[str, Any] | None:
        try:
            raw = await self._r.get(self._key(canonical_match_id))
        except Exception:
            logger.exception(
                "match_context_get_failed",
                extra={"canonical_match_id": str(canonical_match_id)},
            )
            return None
        if raw is None:
            return None
        try:
            return orjson.loads(raw)
        except Exception:
            logger.exception(
                "match_context_decode_failed",
                extra={"canonical_match_id": str(canonical_match_id)},
            )
            return None
