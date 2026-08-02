"""Windowed historical trend detection over 5, 10 and scope baselines."""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Callable

from atlas.intelligence.contracts import (
    EvidenceType,
    RegimeInsight,
    TrendDirection,
    TrendInsight,
)
from atlas.intelligence.evidence_engine import EvidenceEngine
from atlas.intelligence.historical import HistoricalRecord, mean_feature, stable_id
from atlas.intelligence.kernel import EvidenceWindow, TrendID


class HistoricalTrendEngine:
    def __init__(self, evidence: EvidenceEngine | None = None) -> None:
        self._evidence = evidence or EvidenceEngine()

    def detect(
        self,
        rows: list[HistoricalRecord],
        *,
        scope_key: str,
        as_of: datetime,
        regime: RegimeInsight,
    ) -> list[TrendInsight]:
        if len(rows) < 5:
            return []
        specs: list[tuple[str, Callable[[list[HistoricalRecord]], float], float]] = [
            ("draw_trend", _draw_rate, 0.06),
            ("goal_trend", _goal_rate, 0.25),
            ("volatility_trend", _goal_volatility, 0.20),
        ]
        if sum(row.has_odds for row in rows) >= 5:
            specs.extend(
                [
                    (
                        "favorite_trend",
                        lambda values: mean_feature(
                            [row for row in values if row.has_odds],
                            "favorite_strength",
                        ),
                        0.04,
                    ),
                    ("market_trend", _market_shift, 0.01),
                ]
            )
        return [
            self._trend(
                rows,
                scope_key=scope_key,
                as_of=as_of,
                regime=regime,
                trend_type=name,
                metric=metric,
                material_delta=threshold,
            )
            for name, metric, threshold in specs
        ]

    def _trend(
        self,
        rows: list[HistoricalRecord],
        *,
        scope_key: str,
        as_of: datetime,
        regime: RegimeInsight,
        trend_type: str,
        metric: Callable[[list[HistoricalRecord]], float],
        material_delta: float,
    ) -> TrendInsight:
        baseline = metric(rows)
        options = []
        for size in (5, 10):
            if len(rows) >= size:
                value = metric(rows[-size:])
                options.append((abs(value - baseline), size, value))
        _, size, recent = max(options)
        delta = recent - baseline
        if delta > material_delta:
            direction = TrendDirection.rising
        elif delta < -material_delta:
            direction = TrendDirection.falling
        else:
            direction = TrendDirection.stable
        strength = min(1.0, abs(delta) / max(material_delta * 3, 1e-9))
        confidence = min(0.95, 0.5 + 0.025 * size + 0.2 * min(1.0, len(rows) / 100))
        evidence = self._evidence.create(
            scope_key=scope_key,
            evidence_type=(
                EvidenceType.market if "market" in trend_type or "favorite" in trend_type
                else EvidenceType.historical
            ),
            source="windowed certified history",
            description=(
                f"{trend_type}: latest {size} value {recent:.4f} versus "
                f"season/competition baseline {baseline:.4f}"
            ),
            observed_at=as_of,
            weight=0.85,
            confidence=confidence,
            attributes={
                "window_matches": size,
                "recent_value": round(recent, 6),
                "baseline_value": round(baseline, 6),
                "delta": round(delta, 6),
                "baselines": ["season", "competition"],
            },
        )
        return TrendInsight(
            trend_id=TrendID(stable_id(scope_key, "trend", trend_type)),
            trend_type=trend_type,
            direction=direction,
            strength=round(strength, 6),
            confidence=round(confidence, 6),
            evidence=[evidence],
            regime=regime.regime_id,
            window=EvidenceWindow(
                start=rows[-size].kickoff_at,
                end=min(as_of, rows[-1].kickoff_at),
            ),
        )


def _draw_rate(rows: list[HistoricalRecord]) -> float:
    return sum(row.label == "DRAW" for row in rows) / max(len(rows), 1)


def _goal_rate(rows: list[HistoricalRecord]) -> float:
    return sum(row.total_goals for row in rows) / max(len(rows), 1)


def _goal_volatility(rows: list[HistoricalRecord]) -> float:
    goals = [row.total_goals for row in rows]
    return statistics.pstdev(goals) if len(goals) > 1 else 0.0


def _market_shift(rows: list[HistoricalRecord]) -> float:
    odds = [row for row in rows if row.has_odds]
    values = []
    for row in odds:
        opening = row.features.get("opening_home")
        closing = row.features.get("closing_home")
        if opening and closing:
            values.append((1.0 / closing) - (1.0 / opening))
    return sum(values) / len(values) if values else 0.0
