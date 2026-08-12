"""Sliding-window occurrence store for event aggregation.

`record` appends an occurrence and returns the count within the window;
`allow_fire` enforces a per-key cooldown so an aggregated signal fires
once per window rather than on every event past the threshold.
"""

from __future__ import annotations

import time
from typing import Protocol

from redis.asyncio import Redis


class AggregationStore(Protocol):
    async def record(self, key: str, now: float, window_seconds: int) -> int:
        """Append an occurrence at `now`; return the count within the
        trailing `window_seconds`."""
        ...

    async def allow_fire(self, key: str, now: float, cooldown_seconds: int) -> bool:
        """Return True at most once per `cooldown_seconds` per key."""
        ...


class InMemoryAggregationStore:
    """In-memory store for tests / single instance."""

    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}
        self._fired: dict[str, float] = {}

    async def record(self, key: str, now: float, window_seconds: int) -> int:
        bucket = self._events.setdefault(key, [])
        bucket.append(now)
        cutoff = now - window_seconds
        bucket[:] = [t for t in bucket if t >= cutoff]
        return len(bucket)

    async def allow_fire(self, key: str, now: float, cooldown_seconds: int) -> bool:
        last = self._fired.get(key)
        if last is not None and now - last < cooldown_seconds:
            return False
        self._fired[key] = now
        return True


class RedisAggregationStore:
    """Redis-backed store using a sorted set per key (score = timestamp)
    for the sliding window, and a cooldown key with SET NX EX for the
    fire gate. Shared across Atlas instances.
    """

    def __init__(self, redis: Redis, *, key_prefix: str = "atlas:agg:") -> None:
        self._r = redis
        self._prefix = key_prefix

    def _window_key(self, key: str) -> str:
        return f"{self._prefix}w:{key}"

    def _fire_key(self, key: str) -> str:
        return f"{self._prefix}f:{key}"

    async def record(self, key: str, now: float, window_seconds: int) -> int:
        wkey = self._window_key(key)
        cutoff = now - window_seconds
        pipe = self._r.pipeline()
        # Unique member per occurrence so identical timestamps don't collapse.
        member = f"{now:.6f}"
        pipe.zadd(wkey, {member: now})
        pipe.zremrangebyscore(wkey, "-inf", cutoff)
        pipe.zcard(wkey)
        pipe.expire(wkey, window_seconds * 2)
        results = await pipe.execute()
        return int(results[2])

    async def allow_fire(self, key: str, now: float, cooldown_seconds: int) -> bool:
        # SET NX EX: succeeds only when no live cooldown key exists.
        ok = await self._r.set(
            self._fire_key(key), f"{now:.6f}", nx=True, ex=max(1, cooldown_seconds)
        )
        return bool(ok)


def now_seconds() -> float:
    return time.time()
