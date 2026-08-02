"""Competition Regime Detection — Intelligence Maturity Part 5.

Classifies the current state of a competition from its
CompetitionProfile. Fully rule-based with configurable thresholds —
the first matching rule in precedence order wins, so classification
is deterministic and auditable.

Precedence (most specific signal first):

  FRAGMENTED      — fragmentation ≥ fragmented_min
  VOLATILE        — volatility ≥ volatile_min
  EVENT_DRIVEN    — sentinel share ≥ event_min
  MOMENTUM_DRIVEN — pulse share ≥ momentum_min
  HIGH_CONFIDENCE — mean confidence ≥ high_confidence_min
  LOW_CONFIDENCE  — mean confidence ≤ low_confidence_max
  STABLE          — everything else
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.intelligence.competition import CompetitionProfile
from atlas.registry.models import CompetitionRegimeRow

logger = logging.getLogger(__name__)

COMPETITION_REGIMES_TOTAL = Counter(
    "competition_regimes_total",
    "Competition regime classifications recorded.",
    ["regime"],
)


class CompetitionRegime(str, enum.Enum):
    STABLE = "STABLE"
    VOLATILE = "VOLATILE"
    FRAGMENTED = "FRAGMENTED"
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MOMENTUM_DRIVEN = "MOMENTUM_DRIVEN"
    EVENT_DRIVEN = "EVENT_DRIVEN"


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    """Configurable classification thresholds (Part 5 requirement)."""

    fragmented_min: float = 0.30
    volatile_min: float = 0.30
    event_min: float = 0.40
    momentum_min: float = 0.40
    high_confidence_min: float = 0.75
    low_confidence_max: float = 0.45


class RegimeEngine:
    """Pure classification + append-only persistence of changes."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        thresholds: RegimeThresholds | None = None,
    ) -> None:
        self._sf = session_factory
        self._t = thresholds or RegimeThresholds()

    def classify(self, profile: CompetitionProfile) -> CompetitionRegime:
        t = self._t
        if profile.fragmentation >= t.fragmented_min:
            return CompetitionRegime.FRAGMENTED
        if profile.volatility >= t.volatile_min:
            return CompetitionRegime.VOLATILE
        if profile.event_share >= t.event_min:
            return CompetitionRegime.EVENT_DRIVEN
        if profile.momentum_share >= t.momentum_min:
            return CompetitionRegime.MOMENTUM_DRIVEN
        if profile.confidence >= t.high_confidence_min:
            return CompetitionRegime.HIGH_CONFIDENCE
        if profile.confidence <= t.low_confidence_max:
            return CompetitionRegime.LOW_CONFIDENCE
        return CompetitionRegime.STABLE

    async def current(self, competition_id: UUID) -> CompetitionRegime | None:
        """The latest recorded regime, or None when never classified."""
        stmt = (
            select(CompetitionRegimeRow.regime)
            .where(CompetitionRegimeRow.competition_id == competition_id)
            .order_by(CompetitionRegimeRow.computed_at.desc())
            .limit(1)
        )
        async with self._sf() as session:
            value = (await session.execute(stmt)).scalar_one_or_none()
        return CompetitionRegime(value) if value else None

    async def observe(
        self,
        profile: CompetitionProfile,
        *,
        now: datetime | None = None,
    ) -> tuple[CompetitionRegime, bool]:
        """Classify + persist when the regime CHANGED (append-only
        history). Returns (regime, changed)."""
        regime = self.classify(profile)
        previous = await self.current(profile.competition_id)
        changed = previous != regime
        if changed:
            async with self._sf() as session:
                session.add(CompetitionRegimeRow(
                    competition_id=profile.competition_id,
                    regime=regime.value,
                    profile=profile.to_wire(),
                    computed_at=now or datetime.now(timezone.utc),
                ))
                await session.commit()
            COMPETITION_REGIMES_TOTAL.labels(regime=regime.value).inc()
            logger.info(
                "competition_regime_changed",
                extra={
                    "competition_id": str(profile.competition_id),
                    "from": previous.value if previous else None,
                    "to": regime.value,
                },
            )
        return regime, changed
