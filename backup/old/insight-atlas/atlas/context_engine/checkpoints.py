"""Minute-checkpoint tracking for time-driven recalculation.

Each match fires recalculation at configurable minute checkpoints
(15/30/45/60/75/90). The tracker remembers which checkpoints already
fired per match so a given checkpoint triggers exactly once even though
events arrive continuously. Redis-backed in production; in-memory for
tests.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis

DEFAULT_CHECKPOINTS: tuple[int, ...] = (15, 30, 45, 60, 75, 90)


class CheckpointStore(Protocol):
    async def fire_once(self, match_id: UUID, checkpoint: int, ttl_seconds: int) -> bool:
        """Return True the first time (match, checkpoint) is seen, else
        False (already fired)."""
        ...


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._fired: set[str] = set()

    async def fire_once(self, match_id: UUID, checkpoint: int, ttl_seconds: int) -> bool:
        key = f"{match_id}:{checkpoint}"
        if key in self._fired:
            return False
        self._fired.add(key)
        return True


class RedisCheckpointStore:
    def __init__(self, redis: Redis, *, key_prefix: str = "atlas:ctx:cp:") -> None:
        self._r = redis
        self._prefix = key_prefix

    async def fire_once(self, match_id: UUID, checkpoint: int, ttl_seconds: int) -> bool:
        # SET NX: first writer wins; the key self-expires after the match.
        ok = await self._r.set(
            f"{self._prefix}{match_id}:{checkpoint}", "1", nx=True, ex=max(1, ttl_seconds)
        )
        return bool(ok)


class CheckpointTracker:
    """Resolves which checkpoints have newly become due for a match."""

    def __init__(
        self,
        store: CheckpointStore,
        *,
        checkpoints: tuple[int, ...] = DEFAULT_CHECKPOINTS,
        ttl_seconds: int = 4 * 3600,
    ) -> None:
        self._store = store
        self._checkpoints = tuple(sorted(checkpoints))
        self._ttl = ttl_seconds

    async def due(self, match_id: UUID, minute: int) -> list[int]:
        """Return the checkpoints at or below `minute` that fire now (each
        exactly once for the match)."""
        out: list[int] = []
        for cp in self._checkpoints:
            if cp > minute:
                break
            if await self._store.fire_once(match_id, cp, self._ttl):
                out.append(cp)
        return out
