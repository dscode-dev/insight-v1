"""Historical market-behavior intelligence.

The engine describes movement and disagreement.  It does not emit outcome
probabilities, betting value, recommendations, or picks.
"""

from __future__ import annotations

import statistics
from datetime import datetime

from atlas.intelligence.contracts import (
    Evidence,
    EvidenceType,
    MarketInsight,
    MarketMovement,
    MarketMovementDirection,
)
from atlas.intelligence.evidence_engine import EvidenceEngine
from atlas.intelligence.historical import HistoricalRecord, mean_feature, stable_id
from atlas.intelligence.kernel import InsightID


class MarketIntelligenceEngine:
    def __init__(self, evidence: EvidenceEngine | None = None) -> None:
        self._evidence = evidence or EvidenceEngine()

    def analyze(
        self, rows: list[HistoricalRecord], *, scope_key: str, as_of: datetime
    ) -> tuple[MarketInsight | None, list[Evidence]]:
        odds_rows = [row for row in rows if row.has_odds]
        if not odds_rows:
            return None, []

        # ONE pass over the odds rows. `_favorite_shift` and
        # `_movement_dispersion` each called `_implied_movements(row)`
        # internally (6 float lookups + 2 normalisations per row), so
        # the rows were fully re-derived twice per report.
        shifts: list[float] = []
        disagreement_values: list[float] = []
        for row in odds_rows:
            movements = _implied_movements(row)
            if movements is None:
                continue
            open_prob, close_prob = movements
            favorite = max(range(3), key=open_prob.__getitem__)
            shifts.append(close_prob[favorite] - open_prob[favorite])
            disagreement_values.append(
                statistics.pstdev(
                    [close_prob[index] - open_prob[index] for index in range(3)]
                )
            )
        implied_shift = sum(shifts) / len(shifts) if shifts else 0.0
        abs_shifts = [abs(value) for value in shifts]
        volatility = min(
            1.0,
            (statistics.pstdev(shifts) / 0.08 if len(shifts) > 1 else 0.0),
        )
        disagreement = min(
            1.0,
            (
                sum(disagreement_values) / len(disagreement_values) / 0.08
                if disagreement_values
                else 0.0
            ),
        )
        favorite_pressure = min(1.0, mean_feature(odds_rows, "favorite_strength"))
        movement_strength = min(
            1.0, (sum(abs_shifts) / len(abs_shifts) / 0.12 if abs_shifts else 0.0)
        )
        if implied_shift > 0.005:
            direction = MarketMovementDirection.shortening
        elif implied_shift < -0.005:
            direction = MarketMovementDirection.drifting
        else:
            direction = MarketMovementDirection.stable
        coverage = len(odds_rows) / len(rows)
        confidence = min(0.95, 0.45 + 0.4 * coverage + 0.15 * min(1.0, len(odds_rows) / 100))
        evidence = [
            self._evidence.create(
                scope_key=scope_key,
                evidence_type=EvidenceType.market,
                source="certified historical odds",
                description=(
                    f"{len(odds_rows)} odds-bearing matches across {len(rows)} "
                    f"historical matches"
                ),
                observed_at=as_of,
                weight=0.9,
                confidence=confidence,
                attributes={"odds_coverage": round(coverage, 6)},
            ),
            self._evidence.create(
                scope_key=scope_key,
                evidence_type=EvidenceType.market,
                source="opening and closing odds",
                description=(
                    f"mean favorite implied shift {implied_shift:+.4f}; "
                    f"market movement disagreement proxy {disagreement:.4f}"
                ),
                observed_at=as_of,
                weight=0.85,
                confidence=confidence,
                attributes={
                    "implied_shift": round(implied_shift, 6),
                    "volatility": round(volatility, 6),
                    "disagreement": round(disagreement, 6),
                },
            ),
        ]
        return (
            MarketInsight(
                insight_id=InsightID(stable_id(scope_key, "market")),
                movement=MarketMovement(
                    direction=direction,
                    strength=round(movement_strength, 6),
                    outcome="historical favorite",
                ),
                volatility=round(volatility, 6),
                disagreement=round(disagreement, 6),
                favorite_pressure=round(favorite_pressure, 6),
                implied_shift=round(max(-1.0, min(1.0, implied_shift)), 6),
                confidence=round(confidence, 6),
            ),
            evidence,
        )

    def analyze_runtime_odds(
        self,
        odds: dict[str, float | str | None],
        *,
        scope_key: str,
        as_of: datetime,
    ) -> tuple[MarketInsight, list[Evidence]]:
        opening = [
            float(odds["opening_home"]),
            float(odds["opening_draw"]),
            float(odds["opening_away"]),
        ]
        current = [
            float(odds["current_home"]),
            float(odds["current_draw"]),
            float(odds["current_away"]),
        ]
        open_prob = _normalise([1.0 / value for value in opening])
        current_prob = _normalise([1.0 / value for value in current])
        shifts = [
            current_prob[index] - open_prob[index] for index in range(3)
        ]
        favorite = max(range(3), key=open_prob.__getitem__)
        implied_shift = shifts[favorite]
        volatility = min(1.0, statistics.pstdev(shifts) / 0.08)
        disagreement = volatility
        movement_strength = min(1.0, abs(implied_shift) / 0.12)
        direction = (
            MarketMovementDirection.shortening
            if implied_shift > 0.005
            else MarketMovementDirection.drifting
            if implied_shift < -0.005
            else MarketMovementDirection.stable
        )
        confidence = 0.8
        bookmaker = str(odds.get("bookmaker") or "request odds")
        evidence = [
            self._evidence.create(
                scope_key=scope_key,
                evidence_type=EvidenceType.market,
                source=bookmaker,
                description=(
                    "request opening/current odds produced deterministic "
                    f"market movement {direction.value}"
                ),
                observed_at=as_of,
                weight=0.9,
                confidence=confidence,
                attributes={
                    "runtime_request": True,
                    "implied_shift": round(implied_shift, 6),
                    "volatility": round(volatility, 6),
                    "disagreement": round(disagreement, 6),
                },
            )
        ]
        return (
            MarketInsight(
                insight_id=InsightID(stable_id(scope_key, "runtime-market")),
                movement=MarketMovement(
                    direction=direction,
                    strength=round(movement_strength, 6),
                    outcome="market favorite",
                ),
                volatility=round(volatility, 6),
                disagreement=round(disagreement, 6),
                favorite_pressure=round(max(current_prob), 6),
                implied_shift=round(implied_shift, 6),
                confidence=confidence,
            ),
            evidence,
        )


def _favorite_shift(row: HistoricalRecord) -> float | None:
    movements = _implied_movements(row)
    if movements is None:
        return None
    open_prob, close_prob = movements
    favorite = max(range(3), key=open_prob.__getitem__)
    return close_prob[favorite] - open_prob[favorite]


def _movement_dispersion(row: HistoricalRecord) -> float | None:
    movements = _implied_movements(row)
    if movements is None:
        return None
    open_prob, close_prob = movements
    shifts = [close_prob[index] - open_prob[index] for index in range(3)]
    return statistics.pstdev(shifts)


def _implied_movements(
    row: HistoricalRecord,
) -> tuple[list[float], list[float]] | None:
    features = row.features
    opening = [
        features.get("opening_home"),
        features.get("opening_draw"),
        features.get("opening_away"),
    ]
    closing = [
        features.get("closing_home"),
        features.get("closing_draw"),
        features.get("closing_away"),
    ]
    if any(value is None or value <= 0 for value in [*opening, *closing]):
        return None
    open_prob = _normalise([1.0 / float(value) for value in opening])
    close_prob = _normalise([1.0 / float(value) for value in closing])
    return open_prob, close_prob


def _normalise(values: list[float]) -> list[float]:
    total = sum(values)
    return [value / total for value in values]
