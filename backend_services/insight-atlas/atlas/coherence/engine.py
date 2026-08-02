"""Story Coherence — agreement between intelligence dimensions.

Narrative Health (Nexus) measures story QUALITY; coherence measures
AGREEMENT: do market, match, risk and narrative point the same way?

    Pressure ↑  Odds ↑  Narrative ↑   → high coherence
    Pressure ↑  Odds ↓  Narrative ↑   → low coherence

Per match, each dimension's recent trends reduce to a weighted
direction (Σ direction·strength). Coherence is the pairwise sign
agreement among the dimensions that actually have a direction, scaled
by coverage (more dimensions speaking = more meaningful agreement).
Deterministic, persisted (latest per match), metrics-only — never a
publication input.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from itertools import combinations
from uuid import UUID

from prometheus_client import Histogram
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import StoryCoherenceRow
from atlas.trends.models import Trend, TrendCategory
from atlas.trends.repository import TrendRepository

logger = logging.getLogger(__name__)

ATLAS_COHERENCE_SCORE = Histogram(
    "atlas_coherence_score",
    "Distribution of computed story coherence scores.",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# Trend category → coherence dimension.
DIMENSION_OF: dict[TrendCategory, str] = {
    TrendCategory.ninja: "market",
    TrendCategory.pulse: "match",
    TrendCategory.sentinel: "risk",
    TrendCategory.echo: "narrative",
    TrendCategory.oracle: "market",   # historical trends are market-baseline
    TrendCategory.fusion: "match",    # fusions lean on the match story
}


class StoryCoherence(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_match_id: UUID
    score: float = Field(ge=0.0, le=1.0)
    # dimension → weighted direction (Σ direction·strength).
    components: dict[str, float]
    dimensions: int
    computed_at: datetime


class StoryCoherenceEngine:
    def __init__(
        self,
        trends: TrendRepository,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        recent_limit: int = 50,
        now=None,
    ) -> None:
        self._trends = trends
        self._sf = session_factory
        self._limit = recent_limit
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def compute(self, canonical_match_id: UUID) -> StoryCoherence:
        history = await self._trends.history(
            canonical_match_id, limit=self._limit
        )
        components = _components(history)
        score = _agreement(components)
        coherence = StoryCoherence(
            canonical_match_id=canonical_match_id,
            score=score,
            components=components,
            dimensions=len([v for v in components.values() if v != 0.0]),
            computed_at=self._now(),
        )
        await self._persist(coherence)
        ATLAS_COHERENCE_SCORE.observe(score)
        return coherence

    async def _persist(self, c: StoryCoherence) -> None:
        async with self._sf() as session:
            row = await session.get(StoryCoherenceRow, c.canonical_match_id)
            if row is None:
                session.add(
                    StoryCoherenceRow(
                        canonical_match_id=c.canonical_match_id,
                        score=c.score,
                        components=c.components,
                        computed_at=c.computed_at,
                    )
                )
            else:
                row.score = c.score
                row.components = c.components
                row.computed_at = c.computed_at
            await session.commit()


def _components(trends: list[Trend]) -> dict[str, float]:
    """Weighted direction per dimension: Σ direction·strength over the
    match's recent trends."""
    out = {"market": 0.0, "match": 0.0, "risk": 0.0, "narrative": 0.0}
    for t in trends:
        dim = DIMENSION_OF.get(t.category)
        if dim is None or t.direction == 0:
            continue
        out[dim] = round(out[dim] + t.direction * t.strength, 4)
    return out


def _agreement(components: dict[str, float]) -> float:
    """Pairwise sign agreement among non-zero dimensions, scaled by
    coverage. One or zero speaking dimensions → 0.5 (nothing to agree
    or disagree about — neutral)."""
    directed = [v for v in components.values() if v != 0.0]
    if len(directed) < 2:
        return 0.5
    pairs = list(combinations(directed, 2))
    agreeing = sum(1 for a, b in pairs if (a > 0) == (b > 0))
    base = agreeing / len(pairs)
    # Coverage scaling: full agreement across 4 dimensions outranks
    # full agreement across 2.
    coverage = len(directed) / 4.0
    return round(base * (0.5 + 0.5 * coverage), 4)
