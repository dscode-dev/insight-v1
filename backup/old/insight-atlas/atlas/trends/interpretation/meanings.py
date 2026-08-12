"""Semantic meaning mapping — pure deterministic, total over TrendType.

Translates each trend type into a stable semantic meaning slug +
category so downstream consumers (Nexus agents) reason about WHAT a
trend means without re-deriving intelligence. No LLM, no prompts, no
randomness: the same trend always interprets to the same meaning.

`meaning_confidence` is the trend's own confidence — the mapping is a
1:1 deterministic rename, so the certainty of the meaning IS the
certainty of the trend.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from atlas.trends.models import Trend, TrendType


class MeaningCategory(str, enum.Enum):
    market_behavior = "market_behavior"
    match_dynamics = "match_dynamics"
    historical_context = "historical_context"
    risk_assessment = "risk_assessment"
    narrative = "narrative"
    match_structure = "match_structure"


@dataclass(frozen=True, slots=True)
class Interpretation:
    meaning: str
    meaning_category: MeaningCategory
    meaning_confidence: float


# Total mapping — every TrendType MUST have an entry (enforced by test).
MEANING_MAP: dict[TrendType, tuple[str, MeaningCategory]] = {
    # Ninja — market.
    TrendType.market_shift: (
        "market_sentiment_shifting", MeaningCategory.market_behavior),
    TrendType.market_acceleration: (
        "market_movement_accelerating", MeaningCategory.market_behavior),
    TrendType.market_disagreement: (
        "market_consensus_breaking", MeaningCategory.market_behavior),
    TrendType.market_anomaly: (
        "bookmaker_detached_from_market", MeaningCategory.market_behavior),
    # Pulse — momentum.
    TrendType.momentum_shift: (
        "momentum_changing_sides", MeaningCategory.match_dynamics),
    TrendType.pressure_building: (
        "attacking_pressure_accumulating", MeaningCategory.match_dynamics),
    TrendType.tempo_change: (
        "match_tempo_changing", MeaningCategory.match_dynamics),
    TrendType.dominance_pattern: (
        "competitive_control_emerging", MeaningCategory.match_dynamics),
    # Oracle — historical.
    TrendType.historical_pattern: (
        "known_historical_pattern_repeating", MeaningCategory.historical_context),
    TrendType.historical_similarity: (
        "match_resembles_past_encounters", MeaningCategory.historical_context),
    TrendType.historical_deviation: (
        "match_deviating_from_baseline", MeaningCategory.historical_context),
    # Sentinel — impact / risk.
    TrendType.impact_assessment: (
        "high_impact_event_landed", MeaningCategory.risk_assessment),
    TrendType.game_state_change: (
        "match_phase_transition", MeaningCategory.match_structure),
    TrendType.risk_increase: (
        "instability_increasing", MeaningCategory.risk_assessment),
    # Echo — narrative.
    TrendType.narrative_conflict: (
        "public_and_market_disagreement", MeaningCategory.narrative),
    TrendType.sentiment_shift: (
        "community_sentiment_swinging", MeaningCategory.narrative),
    TrendType.community_signal: (
        "community_conviction_forming", MeaningCategory.narrative),
    # Fusion — correlated intelligence.
    TrendType.market_conviction: (
        "market_confidence_increasing", MeaningCategory.market_behavior),
    TrendType.imminent_breakthrough: (
        "sustained_pressure_near_conversion", MeaningCategory.match_dynamics),
    TrendType.risk_escalation: (
        "instability_increasing", MeaningCategory.risk_assessment),
    TrendType.narrative_divergence: (
        "public_and_market_disagreement", MeaningCategory.narrative),
    # Market intelligence (Magnus Absorption, Sprint 1).
    TrendType.market_consensus_growing: (
        "market_agreement_strengthening", MeaningCategory.market_behavior),
    TrendType.market_consensus_weakening: (
        "market_agreement_weakening", MeaningCategory.market_behavior),
    TrendType.market_divergence: (
        "bookmakers_diverging", MeaningCategory.market_behavior),
    TrendType.market_fragmentation: (
        "market_view_fragmented", MeaningCategory.market_behavior),
    TrendType.confidence_acceleration: (
        "market_belief_firming", MeaningCategory.market_behavior),
    TrendType.confidence_decay: (
        "market_belief_fading", MeaningCategory.market_behavior),
    TrendType.volatility_increase: (
        "market_view_churning", MeaningCategory.market_behavior),
    TrendType.volatility_decrease: (
        "market_view_stabilising", MeaningCategory.market_behavior),
    TrendType.sharp_market_move: (
        "coordinated_market_repricing", MeaningCategory.market_behavior),
    TrendType.market_uncertainty: (
        "market_uncertainty_rising", MeaningCategory.market_behavior),
    TrendType.market_reaction: (
        "market_reacting_to_match_events", MeaningCategory.market_behavior),
    # Meta — recurring intelligence (Maturity Sprint 1.5).
    TrendType.market_underestimation: (
        "market_repeatedly_underestimating_team", MeaningCategory.market_behavior),
    TrendType.market_overestimation: (
        "market_repeatedly_overestimating_team", MeaningCategory.market_behavior),
    TrendType.recurring_volatility: (
        "volatility_recurring_in_scope", MeaningCategory.market_behavior),
    TrendType.recurring_confidence_failure: (
        "market_confidence_repeatedly_failing", MeaningCategory.market_behavior),
    TrendType.recurring_sharp_reversal: (
        "sharp_moves_repeatedly_reversing", MeaningCategory.market_behavior),
    TrendType.strong_historical_alignment: (
        "conviction_backed_by_history", MeaningCategory.market_behavior),
    TrendType.structural_volatility: (
        "volatility_is_structural", MeaningCategory.market_behavior),
    TrendType.market_correction: (
        "market_correcting_misprice", MeaningCategory.market_behavior),
}


def interpret(trend: Trend) -> Interpretation:
    """Resolve the semantic meaning of one trend. Total + reproducible."""
    meaning, category = MEANING_MAP[trend.trend_type]
    return Interpretation(
        meaning=meaning,
        meaning_category=category,
        meaning_confidence=round(trend.confidence, 4),
    )
