"""CoherenceWatcher — runs the Story Coherence Engine periodically over
recently active matches (Sprint 3.6 Part 9 execution vehicle)."""

from __future__ import annotations

import logging

from atlas.coherence import StoryCoherenceEngine
from atlas.watchers.base import Observation
from atlas.watchers.series import SeriesStore

logger = logging.getLogger(__name__)


class CoherenceWatcher:
    def __init__(
        self,
        engine: StoryCoherenceEngine,
        store: SeriesStore,
        *,
        window_seconds: int = 1800,
        enabled: bool = True,
        max_matches: int = 50,
    ) -> None:
        self._engine = engine
        self._store = store
        self._window = window_seconds
        self._enabled = enabled
        self._max = max_matches

    def name(self) -> str:
        return "coherence"

    def enabled(self) -> bool:
        return self._enabled

    async def observe(self) -> list[Observation]:
        matches = await self._store.recent_matches(window_seconds=self._window)
        for match_id in matches[: self._max]:
            coherence = await self._engine.compute(match_id)
            logger.debug(
                "atlas_coherence_computed",
                extra={
                    "canonical_match_id": str(match_id),
                    "score": coherence.score,
                    "components": coherence.components,
                },
            )
        # Coherence is observability-only: no observations are emitted
        # into the trend pipeline.
        return []
