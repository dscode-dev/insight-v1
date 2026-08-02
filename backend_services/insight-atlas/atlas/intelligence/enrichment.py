"""Intelligence enrichment — Maturity Sprint 1.5 Parts 2, 7, 8, 9.

One composition point between the trend pipeline and the maturity
engines:

  * record_closures — folds terminal lifecycle instances into the
    append-only outcome log (market memory substrate)
  * trend_fields    — the Contract V4 additions for one trend
    (historical_context, market_memory, competition_context, regime,
    continuation), all deterministic aggregates with a short
    read-through cache so the hot path stays cheap
  * evidence_fields — the compact evidence entries Parts 2 and 7
    mandate ("historical_outcomes", "continuation")

The cache is performance-only: the cached value IS the deterministic
aggregate; expiry just bounds staleness between recomputes.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from atlas.intelligence.competition import CompetitionIntelligenceEngine
from atlas.intelligence.continuation import ContinuationEngine
from atlas.intelligence.historical_outcomes import HistoricalOutcomeEngine
from atlas.intelligence.market_memory import MarketMemoryEngine, Scope
from atlas.intelligence.regimes import RegimeEngine
from atlas.trends.lifecycle.models import TrendInstance
from atlas.trends.models import Trend


class IntelligenceEnricher:
    def __init__(
        self,
        *,
        market_memory: MarketMemoryEngine,
        historical: HistoricalOutcomeEngine,
        continuation: ContinuationEngine,
        competition: CompetitionIntelligenceEngine,
        regimes: RegimeEngine,
        cache_seconds: float = 60.0,
    ) -> None:
        self._memory = market_memory
        self._historical = historical
        self._continuation = continuation
        self._competition = competition
        self._regimes = regimes
        self._cache_seconds = cache_seconds
        self._cache: dict[tuple, tuple[float, Any]] = {}

    # ---- write side -----------------------------------------------------

    async def record_closures(
        self,
        instances: list[TrendInstance],
        competition_id: UUID | None,
    ) -> int:
        """Fold every terminal instance into the outcome log.
        Insert-once per instance: replays are no-ops."""
        recorded = 0
        for inst in instances:
            if inst.current_state.terminal:
                if await self._memory.record_closure(
                    inst, competition_id=competition_id
                ):
                    recorded += 1
        return recorded

    # ---- read side --------------------------------------------------------

    async def _cached(self, key: tuple, loader) -> Any:
        now = time.time()
        hit = self._cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        value = await loader()
        self._cache[key] = (now + self._cache_seconds, value)
        return value

    async def trend_fields(
        self, trend: Trend, *, competition_id: UUID | None
    ) -> dict[str, Any]:
        """The Contract V4 field updates for one trend."""
        historical = await self._cached(
            ("hist", trend.trend_type.value, str(competition_id)),
            lambda: self._historical.profile(
                trend.trend_type, competition_id=competition_id
            ),
        )
        memory = await self._cached(
            ("mem", trend.trend_type.value, str(competition_id)),
            lambda: self._memory.profile(
                trend.trend_type,
                Scope.competition(competition_id)
                if competition_id else Scope.global_(),
            ),
        )
        continuation = await self._cached(
            ("cont", trend.trend_type.value, str(competition_id)),
            lambda: self._continuation.profile(
                trend.trend_type, competition_id=competition_id
            ),
        )
        competition_context: dict[str, Any] = {}
        regime: str | None = None
        if competition_id is not None:
            profile = await self._cached(
                ("comp", str(competition_id)),
                lambda: self._competition.profile(competition_id),
            )
            if profile is not None:
                competition_context = profile.to_wire()
                current = await self._cached(
                    ("regime", str(competition_id)),
                    lambda: self._regimes.current(competition_id),
                )
                regime = current.value if current else None
        return {
            "historical_context": historical.to_wire() if historical else {},
            "market_memory": (
                memory.to_wire() if memory and memory.occurrences else {}
            ),
            "competition_context": competition_context,
            "regime": regime,
            "continuation": continuation.to_wire() if continuation else {},
        }

    @staticmethod
    def evidence_fields(v4_fields: dict[str, Any]) -> dict[str, Any]:
        """Parts 2 + 7: the compact evidence entries."""
        out: dict[str, Any] = {}
        if v4_fields.get("historical_context"):
            out["historical_outcomes"] = v4_fields["historical_context"]
        if v4_fields.get("continuation"):
            out["continuation"] = v4_fields["continuation"]
        return out
