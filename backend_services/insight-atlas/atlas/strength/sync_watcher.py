"""StrengthSyncWatcher — keeps the live team-strength state current.

Registered like `atlas/watchers/janitor.py::ClusterJanitor`: conforms to
the `Watcher` protocol (name/enabled/observe), produces no Observations
(its work is the state-update side effect), runs on the SAME shared
`WatcherScheduler` as the other continuous-observation watchers.

That scheduler applies one interval to every registered watcher
(default 30s — tuned for in-play market/stat drift, not a lake rescan).
Re-parsing Explorer's entire validated lake every 30s would be wasteful,
so this watcher self-throttles with its own, much longer minimum
interval — a cheap in-memory timestamp check, no I/O, when it's not yet
due. `StrengthRepository.record_result`'s own idempotency ledger
(`strength_processed_matches`) makes an eventual full rescan safe
either way; the throttle is purely about not doing needless work.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from atlas.strength.lake import iter_match_results
from atlas.strength.repository import StrengthRepository
from atlas.watchers.base import Observation

logger = logging.getLogger(__name__)

DEFAULT_MIN_SYNC_INTERVAL_SECONDS = 1800.0  # 30 minutes


class StrengthSyncWatcher:
    def __init__(
        self,
        repository: StrengthRepository,
        lake_dir: str,
        *,
        min_sync_interval_seconds: float = DEFAULT_MIN_SYNC_INTERVAL_SECONDS,
        enabled: bool = True,
        now=None,
    ) -> None:
        self._repo = repository
        self._lake_dir = lake_dir
        self._min_interval = min_sync_interval_seconds
        self._enabled = enabled
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._last_sync_at: datetime | None = None

    def name(self) -> str:
        return "strength_sync"

    def enabled(self) -> bool:
        return self._enabled

    async def observe(self) -> list[Observation]:
        applied = await self.sync()
        if applied:
            logger.info("atlas_strength_sync_applied", extra={"count": applied})
        return []

    async def sync(self, *, force: bool = False) -> int:
        """One sync pass. Returns how many NEW match results were
        folded into the state (already-processed matches are skipped by
        the repository's idempotency check, not re-counted here).
        `force=True` bypasses the throttle — used by the manual backfill
        entrypoint and by tests."""
        now = self._now()
        if not force and self._last_sync_at is not None:
            elapsed = (now - self._last_sync_at).total_seconds()
            if elapsed < self._min_interval:
                return 0
        self._last_sync_at = now
        applied = 0
        for result in iter_match_results(self._lake_dir):
            if await self._repo.record_result(result):
                applied += 1
        return applied
