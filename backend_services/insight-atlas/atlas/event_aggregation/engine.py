"""Aggregation policies + engine.

Each policy watches one event category over a sliding window and emits
an aggregated Signal when the occurrence count crosses its threshold,
then cools down for the window so it fires once per burst.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from prometheus_client import Counter

from atlas.event_aggregation.store import AggregationStore, now_seconds
from atlas.event_impact import Impact
from atlas.signal_engine import Signal, SignalType

AGGREGATION_EVENTS_TOTAL = Counter(
    "aggregation_events_total",
    "Aggregated signals emitted by the Event Aggregation engine.",
    ["signal_type", "label"],
)


@dataclass(frozen=True, slots=True)
class AggregationPolicy:
    """Watch `category`; when `threshold` occurrences land within
    `window_seconds`, emit a `signal_type` signal."""

    category: str
    window_seconds: int
    threshold: int
    signal_type: SignalType
    impact: Impact
    label: str


# Configurable defaults (Sprint 6.2 examples).
DEFAULT_AGGREGATION_POLICIES: tuple[AggregationPolicy, ...] = (
    AggregationPolicy(
        category="yellow_card",
        window_seconds=600,  # 10 minutes
        threshold=3,
        signal_type=SignalType.MOMENTUM_SWING,
        impact=Impact.HIGH,
        label="aggressive_match",
    ),
    AggregationPolicy(
        category="pressure_change",
        window_seconds=900,  # 15 minutes
        threshold=3,
        signal_type=SignalType.PRESSURE_SPIKE,
        impact=Impact.HIGH,
        label="sustained_pressure",
    ),
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AggregationEngine:
    def __init__(
        self,
        store: AggregationStore,
        *,
        policies: tuple[AggregationPolicy, ...] = DEFAULT_AGGREGATION_POLICIES,
    ) -> None:
        self._store = store
        self._policies = policies

    async def observe(
        self,
        *,
        canonical_match_id: UUID,
        category: str,
        now: datetime | None = None,
    ) -> list[Signal]:
        """Record one occurrence of `category` for a match and return any
        aggregated signals that just crossed threshold."""
        ts = now_seconds()
        created = now or _utcnow()
        out: list[Signal] = []
        for policy in self._policies:
            if policy.category != category:
                continue
            key = f"{canonical_match_id}:{policy.category}"
            count = await self._store.record(key, ts, policy.window_seconds)
            if count < policy.threshold:
                continue
            if not await self._store.allow_fire(key, ts, policy.window_seconds):
                continue
            signal = Signal(
                signal_type=policy.signal_type,
                canonical_match_id=canonical_match_id,
                confidence=self._confidence(count, policy.threshold),
                impact=policy.impact.label,
                evidence_count=count,
                created_at=created,
                metadata={"aggregation": policy.label, "category": category},
            )
            out.append(signal)
            AGGREGATION_EVENTS_TOTAL.labels(
                signal_type=policy.signal_type.value, label=policy.label
            ).inc()
        return out

    @staticmethod
    def _confidence(count: int, threshold: int) -> float:
        # More evidence than the threshold → higher confidence, capped.
        over = count - threshold
        return round(min(1.0, 0.7 + 0.1 * over), 4)
