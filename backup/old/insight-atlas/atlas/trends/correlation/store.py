"""Recent-trend sighting store for the correlation window.

Keeps the trends seen per match inside a sliding window so a new trend
can find its correlation partners. Redis-backed in production (shared
across instances); in-memory for tests / single instance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import orjson
from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class TrendSighting:
    trend_id: str
    trend_type: str
    direction: int
    strength: float
    confidence: float
    ts: float


class RecentTrendStore(Protocol):
    async def record(
        self, match_id: UUID, sighting: TrendSighting, window_seconds: int
    ) -> None: ...

    async def recent(
        self, match_id: UUID, window_seconds: int
    ) -> list[TrendSighting]: ...


class InMemoryRecentTrendStore:
    def __init__(self) -> None:
        self._by_match: dict[UUID, list[TrendSighting]] = {}

    async def record(
        self, match_id: UUID, sighting: TrendSighting, window_seconds: int
    ) -> None:
        bucket = self._by_match.setdefault(match_id, [])
        bucket.append(sighting)
        cutoff = sighting.ts - window_seconds
        bucket[:] = [s for s in bucket if s.ts >= cutoff]

    async def recent(
        self, match_id: UUID, window_seconds: int
    ) -> list[TrendSighting]:
        cutoff = time.time() - window_seconds
        return [s for s in self._by_match.get(match_id, []) if s.ts >= cutoff]


class RedisRecentTrendStore:
    """Sorted set per match: member = JSON sighting, score = timestamp."""

    def __init__(self, redis: Redis, *, key_prefix: str = "atlas:trendwin:") -> None:
        self._r = redis
        self._prefix = key_prefix

    def _key(self, match_id: UUID) -> str:
        return f"{self._prefix}{match_id}"

    async def record(
        self, match_id: UUID, sighting: TrendSighting, window_seconds: int
    ) -> None:
        key = self._key(match_id)
        member = orjson.dumps(
            {
                "trend_id": sighting.trend_id,
                "trend_type": sighting.trend_type,
                "direction": sighting.direction,
                "strength": sighting.strength,
                "confidence": sighting.confidence,
                "ts": sighting.ts,
            }
        )
        pipe = self._r.pipeline()
        pipe.zadd(key, {member: sighting.ts})
        pipe.zremrangebyscore(key, "-inf", sighting.ts - window_seconds)
        pipe.expire(key, window_seconds * 2)
        await pipe.execute()

    async def recent(
        self, match_id: UUID, window_seconds: int
    ) -> list[TrendSighting]:
        cutoff = time.time() - window_seconds
        raw = await self._r.zrangebyscore(self._key(match_id), cutoff, "+inf")
        out: list[TrendSighting] = []
        for item in raw:
            d = orjson.loads(item)
            out.append(
                TrendSighting(
                    trend_id=d["trend_id"],
                    trend_type=d["trend_type"],
                    direction=int(d["direction"]),
                    strength=float(d["strength"]),
                    confidence=float(d["confidence"]),
                    ts=float(d["ts"]),
                )
            )
        return out
