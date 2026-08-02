"""Deterministic football behavior detection over Atlas intelligence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from atlas.intelligence.contracts import (
    BehaviorPattern,
    BehaviorType,
    EvidenceType,
    IntelligenceSignal,
    MarketInsight,
    PatternHistory,
    RegimeInsight,
    SignalState,
    SimilarityInsight,
    TrendInsight,
    UncertaintyInsight,
)
from atlas.intelligence.evidence_engine import EvidenceEngine
from atlas.intelligence.historical import stable_id


@dataclass(frozen=True, slots=True)
class _Detection:
    behavior_type: BehaviorType
    strength: float
    occurrences: int
    description: str
    source: str
    market_support: float


class BehavioralPatternEngine:
    def __init__(self, evidence: EvidenceEngine | None = None) -> None:
        self._evidence = evidence or EvidenceEngine()

    def detect(
        self,
        *,
        signals: list[IntelligenceSignal],
        signal_states: list[SignalState] | None = None,
        trends: list[TrendInsight],
        regime: RegimeInsight,
        similarity: SimilarityInsight,
        market: MarketInsight | None,
        uncertainty: UncertaintyInsight,
        scope_key: str,
    ) -> list[BehaviorPattern]:
        signal = _signal_lookup(signals, signal_states)
        trend = {item.trend_type: item for item in trends}
        matches = similarity.similar_matches
        sample = len(matches)
        detections: list[_Detection] = []

        under_25 = sum(item.total_goals <= 2 for item in matches)
        under_rate = under_25 / sample if sample else 0.0
        goal_trend = trend.get("goal_trend")
        low_scoring_strength = max(
            under_rate,
            (3.0 - similarity.average_goals) / 1.5,
            (
                goal_trend.strength * 0.8
                if goal_trend and goal_trend.direction.value == "falling"
                else 0.0
            ),
        )
        if similarity.average_goals <= 2.5 or under_rate >= 0.55:
            detections.append(
                _Detection(
                    BehaviorType.low_scoring,
                    _clamp(low_scoring_strength),
                    under_25,
                    (
                        f"{sample} similar matches averaged "
                        f"{similarity.average_goals:.2f} goals; "
                        f"{under_rate:.1%} finished with at most 2 goals"
                    ),
                    "historical similarity memory",
                    market.confidence if market else 0.4,
                )
            )

        draw_signal = signal.get("draw_tendency")
        draw_trend = trend.get("draw_trend")
        draws = similarity.outcome_distribution.draws
        draw_rate = draws / sample if sample else 0.0
        draw_strength = max(
            draw_rate,
            _strength(draw_signal),
            (
                draw_trend.strength * 0.8
                if draw_trend and draw_trend.direction.value == "rising"
                else 0.0
            ),
        )
        if draw_strength >= 0.25:
            detections.append(
                _Detection(
                    BehaviorType.draw_tendency,
                    _clamp(draw_strength),
                    draws,
                    (
                        f"{draws} of {sample} similar matches were draws; "
                        f"current draw tendency strength {draw_strength:.3f}"
                    ),
                    "draw signal and historical similarity",
                    market.confidence if market else 0.4,
                )
            )
        elif sample:
            detections.append(
                _Detection(
                    BehaviorType.draw_resistance,
                    _clamp(1.0 - draw_strength),
                    sample - draws,
                    f"{sample - draws} of {sample} similar matches were not draws",
                    "historical similarity memory",
                    market.confidence if market else 0.4,
                )
            )

        if market and market.favorite_pressure >= 0.5:
            occurrences = sum(
                "market_pressure" in item.shared_signals for item in matches
            )
            detections.append(
                _Detection(
                    BehaviorType.favorite_pressure,
                    market.favorite_pressure,
                    occurrences,
                    (
                        f"favorite pressure {market.favorite_pressure:.3f}; "
                        f"shared in {occurrences} similar contexts"
                    ),
                    "market intelligence and historical similarity",
                    market.confidence,
                )
            )

        volatility_signal = signal.get("competition_volatility")
        volatility_trend = trend.get("volatility_trend")
        volatility = max(
            _strength(volatility_signal),
            (
                volatility_trend.strength * 0.8
                if volatility_trend and volatility_trend.direction.value == "rising"
                else 0.0
            ),
        )
        if volatility >= 0.8:
            volatility_type = BehaviorType.chaotic
            pattern_name = "high_volatility"
            volatility_strength = volatility
        elif volatility >= 0.6:
            volatility_type = BehaviorType.volatile
            pattern_name = "high_volatility"
            volatility_strength = volatility
        else:
            volatility_type = BehaviorType.stable
            pattern_name = "low_volatility"
            volatility_strength = 1.0 - volatility
        volatility_occurrences = sum(
            pattern_name in item.shared_patterns for item in matches
        )
        detections.append(
            _Detection(
                volatility_type,
                _clamp(volatility_strength),
                volatility_occurrences,
                (
                    f"volatility strength {volatility:.3f}; "
                    f"{volatility_occurrences} similar contexts shared "
                    f"{pattern_name.replace('_', ' ')}"
                ),
                "volatility signal and historical similarity",
                market.confidence if market else 0.4,
            )
        )

        if market and market.disagreement >= 0.2:
            occurrences = sum(
                "market_pressure" in item.shared_signals for item in matches
            )
            detections.append(
                _Detection(
                    BehaviorType.market_disagreement,
                    market.disagreement,
                    occurrences,
                    (
                        f"market disagreement {market.disagreement:.3f}; "
                        f"{occurrences} similar contexts shared market pressure"
                    ),
                    "market intelligence",
                    market.confidence,
                )
            )

        cooccurring = [item.behavior_type for item in detections]
        return [
            self._pattern(
                detection,
                similarity=similarity,
                regime=regime,
                uncertainty=uncertainty,
                scope_key=scope_key,
                cooccurring=cooccurring,
            )
            for detection in detections
        ]

    def _pattern(
        self,
        detection: _Detection,
        *,
        similarity: SimilarityInsight,
        regime: RegimeInsight,
        uncertainty: UncertaintyInsight,
        scope_key: str,
        cooccurring: list[BehaviorType],
    ) -> BehaviorPattern:
        sample = similarity.actual_neighbor_count
        evidence_support = min(1.0, sample / 25.0)
        coverage_support = 1.0 - uncertainty.uncertainty_score
        confidence = _clamp(
            0.4 * similarity.confidence
            + 0.25 * evidence_support
            + 0.2 * detection.market_support
            + 0.15 * coverage_support
        )
        pattern_uncertainty = _clamp(
            0.55 * (1.0 - confidence)
            + 0.45 * uncertainty.uncertainty_score
        )
        matching = _matching_matches(detection.behavior_type, similarity)
        competitions = Counter(item.competition for item in matching)
        history = PatternHistory(
            occurrences=detection.occurrences,
            sample_size=sample,
            competition_distribution=dict(sorted(competitions.items())),
            regime_distribution=(
                {regime.regime_type.value: detection.occurrences}
                if detection.occurrences
                else {}
            ),
        )
        evidence = self._evidence.create(
            scope_key=scope_key,
            evidence_type=EvidenceType.behavioral,
            source=detection.source,
            description=detection.description,
            observed_at=uncertainty.created_at,
            weight=0.9,
            confidence=confidence,
            attributes={
                "behavior_type": detection.behavior_type.value,
                "strength": round(detection.strength, 6),
                "occurrences": detection.occurrences,
                "sample_size": sample,
                "similarity_confidence": similarity.confidence,
                "coverage_support": round(coverage_support, 6),
            },
        )
        return BehaviorPattern(
            pattern_id=stable_id(
                scope_key, "behavior", detection.behavior_type.value
            ),
            type=detection.behavior_type,
            confidence=round(confidence, 6),
            uncertainty=round(pattern_uncertainty, 6),
            evidence=[evidence],
            regime=regime.regime_id,
            strength=round(detection.strength, 6),
            history=history,
            cooccurring_patterns=[
                item for item in cooccurring if item != detection.behavior_type
            ],
        )


def _matching_matches(
    behavior_type: BehaviorType, similarity: SimilarityInsight
):
    matches = similarity.similar_matches
    if behavior_type == BehaviorType.low_scoring:
        return [item for item in matches if item.total_goals <= 2]
    if behavior_type == BehaviorType.draw_tendency:
        return [item for item in matches if item.historical_outcome == "DRAW"]
    if behavior_type == BehaviorType.draw_resistance:
        return [item for item in matches if item.historical_outcome != "DRAW"]
    if behavior_type == BehaviorType.favorite_pressure:
        return [
            item for item in matches if "market_pressure" in item.shared_signals
        ]
    if behavior_type in {BehaviorType.volatile, BehaviorType.chaotic}:
        return [
            item for item in matches if "high_volatility" in item.shared_patterns
        ]
    if behavior_type == BehaviorType.stable:
        return [
            item for item in matches if "low_volatility" in item.shared_patterns
        ]
    if behavior_type == BehaviorType.market_disagreement:
        return [
            item for item in matches if "market_pressure" in item.shared_signals
        ]
    return []


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _signal_lookup(
    signals: list[IntelligenceSignal],
    states: list[SignalState] | None,
) -> dict[str, IntelligenceSignal | SignalState]:
    if states is not None:
        active = {
            item.signal_key: item
            for item in states
            if item.active and not item.expired
        }
        active.update({
            item.signal_name: item
            for item in states
            if item.active and not item.expired
        })
        return active
    return {item.signal_name: item for item in signals}


def _strength(signal: IntelligenceSignal | SignalState | None) -> float:
    if signal is None:
        return 0.0
    if isinstance(signal, SignalState):
        return signal.effective_strength
    return signal.strength
