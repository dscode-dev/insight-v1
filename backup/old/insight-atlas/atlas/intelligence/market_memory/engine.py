"""Market Memory Engine — Intelligence Maturity Part 1.

Atlas already tracks every trend lifecycle (confirmations, failures,
expirations). This engine makes Atlas REMEMBER them: every closed
instance lands in the append-only atlas.trend_outcomes log, and
MarketMemoryProfile aggregates that log per trend type and scope
(global / competition / team).

Fully deterministic: the same outcome log always yields the same
profile. Insert-once by instance_id makes recording replay-safe; the
log itself is the audit trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import CanonicalMatchRow, TrendOutcomeRow
from atlas.trends.lifecycle.models import TrendInstance, TrendLifecycleState
from atlas.trends.models import TrendType

logger = logging.getLogger(__name__)

MARKET_MEMORY_TOTAL = Counter(
    "market_memory_total",
    "Closed trend instances recorded into market memory.",
    ["outcome"],
)

_TERMINAL = {
    TrendLifecycleState.CONFIRMED,
    TrendLifecycleState.FAILED,
    TrendLifecycleState.EXPIRED,
}


@dataclass(frozen=True, slots=True)
class Scope:
    """Aggregation scope: global, one competition, or one team."""

    kind: str                 # "global" | "competition" | "team"
    key: str | None = None    # competition uuid str / team name

    @classmethod
    def global_(cls) -> "Scope":
        return cls(kind="global")

    @classmethod
    def competition(cls, competition_id: UUID) -> "Scope":
        return cls(kind="competition", key=str(competition_id))

    @classmethod
    def team(cls, team: str) -> "Scope":
        return cls(kind="team", key=team)


@dataclass(frozen=True, slots=True)
class MarketMemoryProfile:
    trend_type: str
    scope: str
    occurrences: int
    confirmations: int
    failures: int
    expirations: int
    avg_duration_seconds: float
    avg_confidence: float
    avg_strength: float

    @property
    def confirmation_rate(self) -> float | None:
        resolved = self.confirmations + self.failures
        return self.confirmations / resolved if resolved else None

    def to_wire(self) -> dict:
        return {
            "scope": self.scope,
            "occurrences": self.occurrences,
            "confirmations": self.confirmations,
            "failures": self.failures,
            "expirations": self.expirations,
            "avg_duration_seconds": round(self.avg_duration_seconds, 1),
            "avg_confidence": round(self.avg_confidence, 4),
            "avg_strength": round(self.avg_strength, 4),
        }


def _mean_history(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class MarketMemoryEngine:
    """Records closures and serves deterministic memory profiles."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self._sf = session_factory

    async def record_closure(
        self,
        instance: TrendInstance,
        *,
        competition_id: UUID | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Fold one terminal lifecycle instance into memory. Insert-
        once: replaying the same closure is a no-op (returns False)."""
        if instance.current_state not in _TERMINAL:
            return False
        ts = now or datetime.now(timezone.utc)
        home, away = await self._teams_of(instance.canonical_match_id)
        values = {
            "instance_id": instance.instance_id,
            "canonical_match_id": instance.canonical_match_id,
            "competition_id": competition_id,
            "trend_type": instance.trend_type.value,
            "direction": instance.direction,
            "outcome": instance.current_state.value,
            "duration_seconds": max(
                0.0,
                (instance.last_seen_at - instance.created_at).total_seconds(),
            ),
            "avg_confidence": _mean_history(instance.confidence_history),
            "avg_strength": _mean_history(instance.strength_history),
            "observation_count": instance.observation_count,
            "home_team": home,
            "away_team": away,
            "closed_at": ts,
        }
        async with self._sf() as session:
            dialect = session.bind.dialect.name if session.bind else ""
            if dialect == "postgresql":
                stmt = (
                    postgresql.insert(TrendOutcomeRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["instance_id"])
                )
            else:
                stmt = (
                    sqlite.insert(TrendOutcomeRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["instance_id"])
                )
            result = await session.execute(stmt)
            await session.commit()
        inserted = bool(result.rowcount)
        if inserted:
            MARKET_MEMORY_TOTAL.labels(
                outcome=instance.current_state.value
            ).inc()
        return inserted

    async def _teams_of(self, canonical_match_id: UUID) -> tuple[str, str]:
        async with self._sf() as session:
            row = await session.get(CanonicalMatchRow, canonical_match_id)
        if row is None:
            return "", ""
        return row.home_team or "", row.away_team or ""

    async def profile(
        self, trend_type: TrendType, scope: Scope
    ) -> MarketMemoryProfile:
        """Aggregate the outcome log for one trend type in one scope.
        Zero-sample profiles are returned with zeroed stats."""
        conditions = [TrendOutcomeRow.trend_type == trend_type.value]
        if scope.kind == "competition" and scope.key:
            conditions.append(
                TrendOutcomeRow.competition_id == UUID(scope.key)
            )
        elif scope.kind == "team" and scope.key:
            conditions.append(or_(
                TrendOutcomeRow.home_team == scope.key,
                TrendOutcomeRow.away_team == scope.key,
            ))
        stmt = select(
            func.count().label("occurrences"),
            func.sum(case((TrendOutcomeRow.outcome == "confirmed", 1), else_=0)),
            func.sum(case((TrendOutcomeRow.outcome == "failed", 1), else_=0)),
            func.sum(case((TrendOutcomeRow.outcome == "expired", 1), else_=0)),
            func.avg(TrendOutcomeRow.duration_seconds),
            func.avg(TrendOutcomeRow.avg_confidence),
            func.avg(TrendOutcomeRow.avg_strength),
        ).where(*conditions)
        async with self._sf() as session:
            row = (await session.execute(stmt)).one()
        occurrences = int(row[0] or 0)
        scope_label = scope.kind if scope.key is None else f"{scope.kind}:{scope.key}"
        return MarketMemoryProfile(
            trend_type=trend_type.value,
            scope=scope_label,
            occurrences=occurrences,
            confirmations=int(row[1] or 0),
            failures=int(row[2] or 0),
            expirations=int(row[3] or 0),
            avg_duration_seconds=float(row[4] or 0.0),
            avg_confidence=float(row[5] or 0.0),
            avg_strength=float(row[6] or 0.0),
        )
