"""SeriesStore — the evolving-state record watchers observe.

Timestamped float samples per (match, series name): possession, shots,
sentiment, risk-event counts… recorded by the ingestion path as events
flow, read by watchers on their schedule. Also tracks which matches
were recently active so watchers know what to observe.

Redis-backed in production (zsets, shared across instances); in-memory
for tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class Sample:
    ts: float
    value: float


class SeriesStore(Protocol):
    async def record(
        self, match_id: UUID, series: str, value: float, *, ts: float | None = None
    ) -> None: ...

    async def series(
        self, match_id: UUID, series: str, *, window_seconds: int
    ) -> list[Sample]: ...

    async def touch_match(self, match_id: UUID, *, ts: float | None = None) -> None: ...

    async def recent_matches(self, *, window_seconds: int) -> list[UUID]: ...


class InMemorySeriesStore:
    def __init__(self) -> None:
        self._series: dict[tuple[UUID, str], list[Sample]] = {}
        self._matches: dict[UUID, float] = {}

    async def record(
        self, match_id: UUID, series: str, value: float, *, ts: float | None = None
    ) -> None:
        now = ts if ts is not None else time.time()
        self._series.setdefault((match_id, series), []).append(Sample(now, value))
        await self.touch_match(match_id, ts=now)

    async def series(
        self, match_id: UUID, series: str, *, window_seconds: int
    ) -> list[Sample]:
        cutoff = time.time() - window_seconds
        return [s for s in self._series.get((match_id, series), []) if s.ts >= cutoff]

    async def touch_match(self, match_id: UUID, *, ts: float | None = None) -> None:
        self._matches[match_id] = ts if ts is not None else time.time()

    async def recent_matches(self, *, window_seconds: int) -> list[UUID]:
        cutoff = time.time() - window_seconds
        return [m for m, ts in self._matches.items() if ts >= cutoff]


class RedisSeriesStore:
    """zset per (match, series): member "ts:value", score ts. The
    recent-match index is one zset scored by last activity."""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "atlas:watch:",
        retention_seconds: int = 4 * 3600,
    ) -> None:
        self._r = redis
        self._prefix = key_prefix
        self._retention = retention_seconds

    def _skey(self, match_id: UUID, series: str) -> str:
        return f"{self._prefix}s:{match_id}:{series}"

    def _mkey(self) -> str:
        return f"{self._prefix}matches"

    async def record(
        self, match_id: UUID, series: str, value: float, *, ts: float | None = None
    ) -> None:
        now = ts if ts is not None else time.time()
        key = self._skey(match_id, series)
        pipe = self._r.pipeline()
        pipe.zadd(key, {f"{now:.6f}:{value:.6f}": now})
        pipe.zremrangebyscore(key, "-inf", now - self._retention)
        pipe.expire(key, self._retention * 2)
        await pipe.execute()
        await self.touch_match(match_id, ts=now)

    async def series(
        self, match_id: UUID, series: str, *, window_seconds: int
    ) -> list[Sample]:
        cutoff = time.time() - window_seconds
        raw = await self._r.zrangebyscore(
            self._skey(match_id, series), cutoff, "+inf"
        )
        out: list[Sample] = []
        for member in raw:
            text = member.decode() if isinstance(member, bytes) else member
            ts_part, _, value_part = text.partition(":")
            try:
                out.append(Sample(float(ts_part), float(value_part)))
            except ValueError:
                continue
        return out

    async def touch_match(self, match_id: UUID, *, ts: float | None = None) -> None:
        now = ts if ts is not None else time.time()
        pipe = self._r.pipeline()
        pipe.zadd(self._mkey(), {str(match_id): now})
        pipe.zremrangebyscore(self._mkey(), "-inf", now - self._retention)
        await pipe.execute()

    async def recent_matches(self, *, window_seconds: int) -> list[UUID]:
        cutoff = time.time() - window_seconds
        raw = await self._r.zrangebyscore(self._mkey(), cutoff, "+inf")
        out: list[UUID] = []
        for member in raw:
            text = member.decode() if isinstance(member, bytes) else member
            try:
                out.append(UUID(text))
            except ValueError:
                continue
        return out
