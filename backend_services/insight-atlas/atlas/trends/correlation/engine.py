"""TrendCorrelationEngine — window-based deterministic correlation.

For each new trend this tick: record it in the match's sighting
window, then check every rule that includes its type. When the partner
type is present in the window (and direction agreement holds where
required), emit a CorrelatedTrend record + a first-class fusion Trend.
A per-(match, correlation_type) cooldown prevents the same correlation
re-firing on every reinforcing tick.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from prometheus_client import Counter

from atlas.event_aggregation.store import AggregationStore
from atlas.trends.contract import render
from atlas.trends.correlation.models import (
    DEFAULT_CORRELATION_RULES,
    DEFAULT_ENRICHED_RULES,
    CorrelatedTrend,
    CorrelationRule,
    EnrichedCorrelationRule,
)
from atlas.trends.correlation.store import RecentTrendStore, TrendSighting
from atlas.trends.models import CATEGORY_OF, Trend, TrendInputs

logger = logging.getLogger(__name__)

TREND_CORRELATIONS_TOTAL = Counter(
    "trend_correlations_total",
    "Correlated trends detected.",
    ["correlation_type"],
)


class TrendCorrelationEngine:
    def __init__(
        self,
        store: RecentTrendStore,
        *,
        rules: tuple[CorrelationRule, ...] = DEFAULT_CORRELATION_RULES,
        enriched_rules: tuple[EnrichedCorrelationRule, ...] = DEFAULT_ENRICHED_RULES,
        cooldown_store: AggregationStore | None = None,
    ) -> None:
        self._store = store
        self._rules = rules
        self._enriched_rules = enriched_rules
        self._cooldown = cooldown_store

    async def correlate(
        self,
        inputs: TrendInputs,
        trends: list[Trend],
        *,
        now: datetime | None = None,
    ) -> tuple[list[CorrelatedTrend], list[Trend], dict[str, list[str]]]:
        """Record this tick's trends and resolve correlations.

        Returns (correlation records, fusion trends, and a map
        member trend_id → correlation ids it participates in)."""
        ts_now = now or datetime.now(timezone.utc)
        epoch = time.time()
        match_id = inputs.canonical_match_id

        max_window = max((r.window_seconds for r in self._rules), default=600)
        for trend in trends:
            await self._store.record(
                match_id,
                TrendSighting(
                    trend_id=str(trend.trend_id),
                    trend_type=trend.trend_type.value,
                    direction=trend.direction,
                    strength=trend.strength,
                    confidence=trend.confidence,
                    ts=epoch,
                ),
                max_window,
            )

        records: list[CorrelatedTrend] = []
        fusions: list[Trend] = []
        membership: dict[str, list[str]] = {}
        new_types = {t.trend_type for t in trends}

        for rule in self._rules:
            a_type, b_type = rule.members
            # Only evaluate rules touched by this tick's trends.
            if a_type not in new_types and b_type not in new_types:
                continue
            window = await self._store.recent(match_id, rule.window_seconds)
            a = _latest(window, a_type.value)
            b = _latest(window, b_type.value)
            if a is None or b is None:
                continue
            if rule.require_direction_agreement and (
                a.direction == 0 or a.direction != b.direction
            ):
                continue
            if self._cooldown is not None:
                key = f"corr:{match_id}:{rule.rule_id}"
                if not await self._cooldown.allow_fire(
                    key, epoch, rule.window_seconds
                ):
                    continue

            record, fusion = self._build(rule, match_id, a, b, ts_now, inputs)
            records.append(record)
            fusions.append(fusion)
            for member in (a, b):
                membership.setdefault(member.trend_id, []).append(str(record.id))
            TREND_CORRELATIONS_TOTAL.labels(
                correlation_type=rule.correlation_type.value
            ).inc()
            logger.info(
                "trend_correlation_detected",
                extra={
                    "correlation_type": rule.correlation_type.value,
                    "canonical_match_id": str(match_id),
                    "members": [a.trend_id, b.trend_id],
                },
            )
        return records, fusions, membership

    async def correlate_enriched(
        self,
        inputs: TrendInputs,
        trends: list[Trend],
        *,
        now: datetime | None = None,
    ) -> tuple[list[CorrelatedTrend], list[Trend]]:
        """Single-member predicate rules over V4-ENRICHED trends
        (Intelligence Maturity Part 10): a trend type combined with a
        deterministic condition on its historical / regime fields
        produces a fusion. Runs after enrichment, honors the same
        per-(match, correlation_type) cooldown."""
        ts_now = now or datetime.now(timezone.utc)
        epoch = time.time()
        match_id = inputs.canonical_match_id
        records: list[CorrelatedTrend] = []
        fusions: list[Trend] = []
        for rule in self._enriched_rules:
            for trend in trends:
                if trend.trend_type != rule.member:
                    continue
                if not rule.predicate(trend):
                    continue
                if self._cooldown is not None:
                    key = f"corr:{match_id}:{rule.correlation_type.value}"
                    if not await self._cooldown.allow_fire(
                        key, epoch, rule.window_seconds
                    ):
                        continue
                evidence = {
                    "member_ids": [str(trend.trend_id)],
                    "member_types": [trend.trend_type.value],
                    "window_seconds": rule.window_seconds,
                    **rule.evidence_of(trend),
                }
                record = CorrelatedTrend(
                    canonical_match_id=match_id,
                    correlation_type=rule.correlation_type,
                    member_trends=[str(trend.trend_id)],
                    confidence=min(1.0, trend.confidence + 0.1),
                    strength=trend.strength,
                    evidence=evidence,
                    created_at=ts_now,
                )
                fusion = Trend(
                    trend_type=rule.fusion_type,
                    category=CATEGORY_OF[rule.fusion_type],
                    agent="correlation",
                    canonical_match_id=match_id,
                    competition_id=inputs.competition_id,
                    minute=inputs.minute,
                    strength=trend.strength,
                    confidence=min(1.0, trend.confidence + 0.1),
                    direction=trend.direction,
                    evidence={**evidence, "correlation_id": str(record.id)},
                    detected_at=ts_now,
                    correlation_ids=[str(record.id)],
                )
                title, summary = render(fusion)
                fusion = fusion.model_copy(
                    update={"title": title, "summary": summary}
                )
                records.append(record)
                fusions.append(fusion)
                TREND_CORRELATIONS_TOTAL.labels(
                    correlation_type=rule.correlation_type.value
                ).inc()
                break  # one fusion per rule per tick
        return records, fusions

    def _build(
        self,
        rule: CorrelationRule,
        match_id,
        a: TrendSighting,
        b: TrendSighting,
        ts_now: datetime,
        inputs: TrendInputs,
    ) -> tuple[CorrelatedTrend, Trend]:
        # Corroboration: the weakest member's confidence plus a bonus —
        # two agreeing detectors beat either alone, but the chain is
        # only as certain as its weakest link.
        confidence = min(1.0, min(a.confidence, b.confidence) + 0.1)
        strength = (a.strength + b.strength) / 2.0
        direction = a.direction if a.direction == b.direction else 0
        evidence = {
            "member_ids": [a.trend_id, b.trend_id],
            "member_types": [a.trend_type, b.trend_type],
            "window_seconds": rule.window_seconds,
            "member_strengths": [round(a.strength, 4), round(b.strength, 4)],
            "member_confidences": [round(a.confidence, 4), round(b.confidence, 4)],
        }
        record = CorrelatedTrend(
            canonical_match_id=match_id,
            correlation_type=rule.correlation_type,
            member_trends=[a.trend_id, b.trend_id],
            confidence=confidence,
            strength=strength,
            evidence=evidence,
            created_at=ts_now,
        )
        fusion = Trend(
            trend_type=rule.fusion_type,
            category=CATEGORY_OF[rule.fusion_type],
            agent="correlation",
            canonical_match_id=match_id,
            competition_id=inputs.competition_id,
            minute=inputs.minute,
            strength=strength,
            confidence=confidence,
            direction=direction,
            evidence={**evidence, "correlation_id": str(record.id)},
            detected_at=ts_now,
            correlation_ids=[str(record.id)],
        )
        title, summary = render(fusion)
        fusion = fusion.model_copy(update={"title": title, "summary": summary})
        return record, fusion


def _latest(window: list[TrendSighting], trend_type: str) -> TrendSighting | None:
    candidates = [s for s in window if s.trend_type == trend_type]
    return max(candidates, key=lambda s: s.ts) if candidates else None
