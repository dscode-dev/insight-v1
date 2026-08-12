"""Deterministic historical similarity and in-memory retrieval.

Similarity is contextual evidence retrieval.  Candidate matches are always
strictly earlier than the query match; their observed outcomes are returned as
history, never as predicted probabilities.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from atlas.intelligence.contracts import (
    Evidence,
    EvidenceType,
    HistoricalOutcomeDistribution,
    IntelligenceSignal,
    MarketInsight,
    RegimeInsight,
    RegimeType,
    SimilarityInsight,
    SimilarMatch,
    TrendInsight,
)
from atlas.intelligence.evidence_engine import EvidenceEngine
from atlas.intelligence.historical import HistoricalDataset, HistoricalRecord, stable_id
from atlas.intelligence.kernel import SimilarityID, UnitScore

_LEAGUES = {
    "premier_league",
    "la_liga",
    "serie_a",
    "bundesliga",
    "ligue_1",
    "brasileirao_serie_a",
}
_CONTINENTAL = {
    "champions_league",
    "europa_league",
    "libertadores",
    "sudamericana",
}
_INTERNATIONAL = {"world_cup", "euro", "copa_america"}

# ATLAS-SIM-A (v2): rebalanced to fold in team-strength (Elo/attack/
# defense), market microstructure (line_movement, not just the point-in-
# time favorite_strength) and match-context (h2h/standings/rest) signals
# atlas/strength/ now computes live. v1's 7-signal table is FROZEN per
# ATLAS_V1_FROZEN.md and stays available via `atlas-memory-embedding-v1`
# tagged vectors (see atlas/vector_memory) — this table only backs the
# new `-v2` embedding_version, coexisting rather than replacing v1.
_WEIGHTS = {
    "elo_delta": 0.16,
    "home_attack_strength": 0.07,
    "away_attack_strength": 0.07,
    "home_defense_strength": 0.07,
    "away_defense_strength": 0.07,
    "market_pressure": 0.10,
    "line_movement": 0.08,
    "home_form": 0.07,
    "away_form": 0.07,
    "h2h_advantage": 0.05,
    "table_position_gap": 0.05,
    "rest_advantage": 0.04,
    "draw_tendency": 0.04,
    "volatility": 0.03,
    "uncertainty": 0.03,
}
# Signals that are always present (defaulted, never fabricated as a
# stand-in for "unknown" — 0.5/0.0 are genuinely neutral values here).
_ALWAYS_PRESENT = frozenset({
    "elo_delta", "home_attack_strength", "away_attack_strength",
    "home_defense_strength", "away_defense_strength",
    "home_form", "away_form", "draw_tendency", "volatility", "uncertainty",
})
# Signals that may be genuinely inapplicable (no market, no prior
# meetings, unknown standings/rest) — omitted, not defaulted, and the
# missing-data renormalization in `_similarity` drops them pairwise.
_OPTIONAL = frozenset(_WEIGHTS) - _ALWAYS_PRESENT
TOTAL_DIMENSIONS = len(_WEIGHTS)


class MatchSimilarityProfile(BaseModel):
    """Normalized pre-match context used by deterministic memory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    match_id: str
    competition: str
    regime: RegimeType
    kickoff_at: datetime
    elo_delta: float = Field(ge=-1.0, le=1.0)
    home_form: UnitScore
    away_form: UnitScore
    draw_tendency: UnitScore
    market_pressure: UnitScore | None = None
    volatility: UnitScore
    uncertainty: UnitScore
    market_available: bool
    # ATLAS-SIM-A (v2) additions. Attack/defense strength are always
    # present (0.5 = league-average default, same "always present"
    # posture as home_form/draw_tendency). The other four follow
    # market_pressure's existing "None = genuinely inapplicable" pattern.
    home_attack_strength: UnitScore = 0.5
    away_attack_strength: UnitScore = 0.5
    home_defense_strength: UnitScore = 0.5
    away_defense_strength: UnitScore = 0.5
    line_movement: float | None = Field(default=None, ge=-1.0, le=1.0)
    h2h_advantage: float | None = Field(default=None, ge=-1.0, le=1.0)
    table_position_gap: float | None = Field(default=None, ge=-1.0, le=1.0)
    rest_advantage: float | None = Field(default=None, ge=-1.0, le=1.0)
    signals: tuple[str, ...] = ()
    trends: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryHit:
    record: HistoricalRecord
    profile: MatchSimilarityProfile
    score: float
    shared_signals: tuple[str, ...]
    shared_trends: tuple[str, ...]
    shared_patterns: tuple[str, ...]


class HistoricalMemory:
    """Deterministic in-process memory over certified historical records."""

    def __init__(self, dataset: HistoricalDataset) -> None:
        self._dataset = dataset

    def retrieve_similar_contexts(
        self,
        query: MatchSimilarityProfile,
        *,
        limit: int | None = None,
        minimum_score: float = 0.97,
    ) -> list[MemoryHit]:
        hits = []
        for record in self._dataset.records:
            if record.uid == query.match_id or record.kickoff_at >= query.kickoff_at:
                continue
            candidate = profile_from_record(record)
            if candidate.regime != query.regime:
                continue
            if candidate.competition != query.competition:
                continue
            score, shared_signals, shared_patterns = _similarity(query, candidate)
            if score < minimum_score:
                continue
            shared_trends = tuple(
                sorted(set(query.trends).intersection(candidate.trends))
            )
            hits.append(
                MemoryHit(
                    record=record,
                    profile=candidate,
                    score=score,
                    shared_signals=shared_signals,
                    shared_trends=shared_trends,
                    shared_patterns=shared_patterns,
                )
            )
        hits.sort(
            key=lambda hit: (
                -hit.score,
                hit.record.kickoff_at,
                hit.record.uid,
            )
        )
        return hits[:limit] if limit is not None else hits

    def retrieve_similar_regimes(
        self, query: MatchSimilarityProfile, *, limit: int = 100
    ) -> list[HistoricalRecord]:
        return [
            row
            for row in reversed(self._dataset.records)
            if row.kickoff_at < query.kickoff_at
            and structural_regime(row.competition) == query.regime
        ][:limit]

    def retrieve_similar_markets(
        self, query: MatchSimilarityProfile, *, limit: int = 50
    ) -> list[MemoryHit]:
        if not query.market_available:
            return []
        return [
            hit
            for hit in self.retrieve_similar_contexts(query, limit=limit * 2)
            if hit.profile.market_available
        ][:limit]

    def retrieve_similar_trends(
        self, query: MatchSimilarityProfile, *, limit: int = 50
    ) -> list[MemoryHit]:
        return [
            hit
            for hit in self.retrieve_similar_contexts(query, limit=limit * 2)
            if hit.shared_trends
        ][:limit]


class SimilarityEngine:
    def __init__(
        self,
        memory: HistoricalMemory,
        evidence: EvidenceEngine | None = None,
    ) -> None:
        self._memory = memory
        self._evidence = evidence or EvidenceEngine()

    def analyze(
        self,
        query_record: HistoricalRecord,
        *,
        signals: list[IntelligenceSignal],
        market: MarketInsight | None,
        regime: RegimeInsight,
        trends: list[TrendInsight],
        scope_key: str,
        limit: int | None = None,
        minimum_score: float = 0.97,
    ) -> SimilarityInsight:
        query = profile_from_intelligence(
            query_record,
            signals=signals,
            market=market,
            regime=regime,
            trends=trends,
        )
        hits = self._memory.retrieve_similar_contexts(
            query, limit=limit, minimum_score=minimum_score
        )
        outcomes = Counter(hit.record.label for hit in hits)
        trend_counts = Counter(
            trend for hit in hits for trend in hit.profile.trends
        )
        regime_counts = Counter(hit.profile.regime.value for hit in hits)
        shared_signals = _common(
            [signal for hit in hits for signal in hit.shared_signals], len(hits)
        )
        shared_trends = _common(
            [trend for hit in hits for trend in hit.shared_trends], len(hits)
        )
        shared_patterns = _common(
            [pattern for hit in hits for pattern in hit.shared_patterns], len(hits)
        )
        average_score = sum(hit.score for hit in hits) / len(hits) if hits else 0.0
        dimensional_coverage = _dimension_coverage(query)
        neighborhood_diversity = (
            len({_profile_signature(hit.profile) for hit in hits}) / len(hits)
            if hits
            else 0.0
        )
        diversity_factor = 0.7 + 0.3 * neighborhood_diversity
        confidence = min(
            0.95,
            average_score
            * min(1.0, len(hits) / 25)
            * dimensional_coverage,
            average_score * diversity_factor * dimensional_coverage,
        )
        evidence = self._similarity_evidence(
            query=query,
            hits=hits,
            scope_key=scope_key,
            confidence=confidence,
            shared_patterns=shared_patterns,
            neighborhood_diversity=neighborhood_diversity,
            minimum_score=minimum_score,
        )
        return SimilarityInsight(
            similarity_id=SimilarityID(stable_id(scope_key, "similarity")),
            similar_matches=[
                SimilarMatch(
                    match_id=stable_id("match", hit.record.uid),
                    competition=hit.record.competition,
                    kickoff_at=hit.record.kickoff_at,
                    home=hit.record.home,
                    away=hit.record.away,
                    similarity_score=round(hit.score, 6),
                    shared_patterns=list(hit.shared_patterns),
                    shared_signals=list(hit.shared_signals),
                    shared_trends=list(hit.shared_trends),
                    historical_outcome=hit.record.label,
                    total_goals=hit.record.total_goals,
                )
                for hit in hits
            ],
            similarity_score=round(average_score, 6),
            minimum_similarity=round(
                min((hit.score for hit in hits), default=0.0), 6
            ),
            maximum_similarity=round(
                max((hit.score for hit in hits), default=0.0), 6
            ),
            similarity_threshold=minimum_score,
            actual_neighbor_count=len(hits),
            outcome_distribution=HistoricalOutcomeDistribution(
                home_wins=outcomes["HOME_WIN"],
                draws=outcomes["DRAW"],
                away_wins=outcomes["AWAY_WIN"],
            ),
            shared_patterns=shared_patterns,
            shared_signals=shared_signals,
            shared_trends=shared_trends,
            trend_distribution=dict(sorted(trend_counts.items())),
            regime_distribution=dict(sorted(regime_counts.items())),
            average_goals=round(
                sum(hit.record.total_goals for hit in hits) / len(hits)
                if hits
                else 0.0,
                6,
            ),
            evidence=evidence,
            confidence=round(confidence, 6),
        )

    def _similarity_evidence(
        self,
        *,
        query: MatchSimilarityProfile,
        hits: list[MemoryHit],
        scope_key: str,
        confidence: float,
        shared_patterns: list[str],
        neighborhood_diversity: float,
        minimum_score: float,
    ) -> list[Evidence]:
        if not hits:
            return [
                self._evidence.create(
                    scope_key=scope_key,
                    evidence_type=EvidenceType.historical,
                    source="deterministic historical memory",
                    description="no historical contexts met the similarity threshold",
                    observed_at=query.kickoff_at,
                    weight=0.8,
                    confidence=0.0,
                    attributes={"minimum_similarity": minimum_score},
                )
            ]
        return [
            self._evidence.create(
                scope_key=scope_key,
                evidence_type=EvidenceType.historical,
                source="deterministic historical memory",
                description=(
                    f"{len(hits)} similar prior contexts; mean similarity "
                    f"{sum(hit.score for hit in hits) / len(hits):.1%}"
                ),
                observed_at=query.kickoff_at,
                weight=0.9,
                confidence=confidence,
                attributes={
                    "strictly_prior": True,
                    "same_regime_filter": query.regime.value,
                    "shared_patterns": shared_patterns,
                    "neighborhood_diversity": round(neighborhood_diversity, 6),
                    "minimum_similarity": minimum_score,
                    "actual_neighbor_count": len(hits),
                    "minimum_retained_similarity": round(
                        min(hit.score for hit in hits), 6
                    ),
                    "maximum_retained_similarity": round(
                        max(hit.score for hit in hits), 6
                    ),
                },
            )
        ]


def profile_from_intelligence(
    record: HistoricalRecord,
    *,
    signals: list[IntelligenceSignal],
    market: MarketInsight | None,
    regime: RegimeInsight,
    trends: list[TrendInsight],
) -> MatchSimilarityProfile:
    signal_names = {signal.signal_name for signal in signals}
    profile_trends = _profile_trends(record)
    declared_trends = {trend.trend_type for trend in trends}
    return MatchSimilarityProfile(
        match_id=record.uid,
        competition=record.competition,
        regime=regime.regime_type,
        kickoff_at=record.kickoff_at,
        elo_delta=_elo(record),
        home_form=_feature(record, "home_points_5"),
        away_form=_feature(record, "away_points_5"),
        draw_tendency=_feature(record, "draw_rate_mean_5"),
        market_pressure=(
            _feature(record, "favorite_strength") if record.has_odds else None
        ),
        volatility=_record_volatility(record),
        uncertainty=_uncertainty(record),
        market_available=record.has_odds and market is not None,
        home_attack_strength=_feature_default(record, "home_attack_strength", 0.5),
        away_attack_strength=_feature_default(record, "away_attack_strength", 0.5),
        home_defense_strength=_feature_default(record, "home_defense_strength", 0.5),
        away_defense_strength=_feature_default(record, "away_defense_strength", 0.5),
        line_movement=_optional_signed_feature(record, "line_movement"),
        h2h_advantage=_optional_signed_feature(record, "h2h_advantage"),
        table_position_gap=_optional_signed_feature(record, "table_position_gap"),
        rest_advantage=_optional_signed_feature(record, "rest_advantage"),
        signals=tuple(sorted(signal_names)),
        trends=tuple(sorted(profile_trends.intersection(declared_trends))),
    )


def profile_from_record(record: HistoricalRecord) -> MatchSimilarityProfile:
    signal_names = [
        "home_form",
        "away_form",
        "momentum",
        "draw_tendency",
        "scoring_tendency",
        "competition_volatility",
    ]
    if record.has_odds:
        signal_names.extend(
            ["favorite_pressure", "market_consensus", "market_disagreement"]
        )
    return MatchSimilarityProfile(
        match_id=record.uid,
        competition=record.competition,
        regime=structural_regime(record.competition),
        kickoff_at=record.kickoff_at,
        elo_delta=_elo(record),
        home_form=_feature(record, "home_points_5"),
        away_form=_feature(record, "away_points_5"),
        draw_tendency=_feature(record, "draw_rate_mean_5"),
        market_pressure=(
            _feature(record, "favorite_strength") if record.has_odds else None
        ),
        volatility=_record_volatility(record),
        uncertainty=_uncertainty(record),
        market_available=record.has_odds,
        home_attack_strength=_feature_default(record, "home_attack_strength", 0.5),
        away_attack_strength=_feature_default(record, "away_attack_strength", 0.5),
        home_defense_strength=_feature_default(record, "home_defense_strength", 0.5),
        away_defense_strength=_feature_default(record, "away_defense_strength", 0.5),
        line_movement=_optional_signed_feature(record, "line_movement"),
        h2h_advantage=_optional_signed_feature(record, "h2h_advantage"),
        table_position_gap=_optional_signed_feature(record, "table_position_gap"),
        rest_advantage=_optional_signed_feature(record, "rest_advantage"),
        signals=tuple(sorted(signal_names)),
        trends=tuple(sorted(_profile_trends(record))),
    )


def structural_regime(competition: str) -> RegimeType:
    if competition in _LEAGUES:
        return RegimeType.league
    if competition in _CONTINENTAL:
        return RegimeType.continental
    if competition in _INTERNATIONAL:
        return RegimeType.international
    return RegimeType.low_information


def _similarity(
    query: MatchSimilarityProfile, candidate: MatchSimilarityProfile
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    values = {
        "elo_delta": (_signed_to_unit(query.elo_delta), _signed_to_unit(candidate.elo_delta)),
        "home_form": (query.home_form, candidate.home_form),
        "away_form": (query.away_form, candidate.away_form),
        "draw_tendency": (query.draw_tendency, candidate.draw_tendency),
        "volatility": (query.volatility, candidate.volatility),
        "uncertainty": (query.uncertainty, candidate.uncertainty),
        "home_attack_strength": (query.home_attack_strength, candidate.home_attack_strength),
        "away_attack_strength": (query.away_attack_strength, candidate.away_attack_strength),
        "home_defense_strength": (query.home_defense_strength, candidate.home_defense_strength),
        "away_defense_strength": (query.away_defense_strength, candidate.away_defense_strength),
    }
    if query.market_pressure is not None and candidate.market_pressure is not None:
        values["market_pressure"] = (query.market_pressure, candidate.market_pressure)
    for name in ("line_movement", "h2h_advantage", "table_position_gap", "rest_advantage"):
        left, right = getattr(query, name), getattr(candidate, name)
        if left is not None and right is not None:
            values[name] = (_signed_to_unit(left), _signed_to_unit(right))
    weighted = sum(
        _WEIGHTS[name] * (1.0 - abs(left - right))
        for name, (left, right) in values.items()
    )
    denominator = sum(_WEIGHTS[name] for name in values)
    numeric = weighted / denominator
    competition_bonus = 0.05 if query.competition == candidate.competition else 0.0
    market_penalty = (
        0.08 if query.market_available != candidate.market_available else 0.0
    )
    score = max(0.0, min(1.0, numeric + competition_bonus - market_penalty))
    shared_signals = tuple(
        sorted(
            name
            for name, (left, right) in values.items()
            if abs(left - right) <= 0.12
        )
    )
    shared_patterns = tuple(
        sorted(set(_patterns(query)).intersection(_patterns(candidate)))
    )
    return score, shared_signals, shared_patterns


def _patterns(profile: MatchSimilarityProfile) -> set[str]:
    patterns = {f"same_{profile.regime.value}_regime"}
    if profile.home_form >= 0.6:
        patterns.add("strong_home_form")
    if profile.away_form >= 0.6:
        patterns.add("strong_away_form")
    if profile.draw_tendency >= 0.28:
        patterns.add("high_draw_tendency")
    if profile.volatility >= 0.65:
        patterns.add("high_volatility")
    else:
        patterns.add("low_volatility")
    if profile.market_pressure is not None and profile.market_pressure >= 0.6:
        patterns.add("favorite_pressure")
    if profile.uncertainty >= 0.5:
        patterns.add("high_uncertainty")
    return patterns


def _profile_trends(record: HistoricalRecord) -> set[str]:
    trends = set()
    if _feature(record, "draw_rate_mean_5") >= 0.28:
        trends.add("draw_trend")
    if _feature(record, "expected_total_goals_5") >= 2.8:
        trends.add("goal_trend")
    if _record_volatility(record) >= 0.65:
        trends.add("volatility_trend")
    if record.has_odds:
        trends.add("market_trend")
        if _feature(record, "favorite_strength") >= 0.6:
            trends.add("favorite_trend")
    return trends


def _feature(record: HistoricalRecord, name: str) -> float:
    return max(0.0, min(1.0, float(record.features.get(name, 0.0))))


def _feature_default(record: HistoricalRecord, name: str, default: float) -> float:
    """Like `_feature`, but the fallback for an absent key is `default`
    (e.g. 0.5 = neutral) instead of 0.0 — 0.0 would read as "worst
    possible" for a strength ratio, not "unknown"."""
    if name not in record.features:
        return default
    return max(0.0, min(1.0, float(record.features[name])))


def _optional_signed_feature(record: HistoricalRecord, name: str) -> float | None:
    """A signed [-1, 1] feature that's genuinely absent (not just
    zero) when the key isn't present — never fabricated."""
    if name not in record.features:
        return None
    return max(-1.0, min(1.0, float(record.features[name])))


def _elo(record: HistoricalRecord) -> float:
    return max(-1.0, min(1.0, float(record.features.get("elo_difference", 0.0))))


def _signed_to_unit(value: float) -> float:
    """Maps any signed [-1, 1] value onto [0, 1] for the weighted-diff
    comparison in `_similarity` — used for elo_delta and every new
    signed derived signal (line_movement, h2h_advantage, ...)."""
    return (value + 1.0) / 2.0


def _record_volatility(record: HistoricalRecord) -> float:
    if record.has_odds:
        return _feature(record, "market_entropy")
    expected = float(record.features.get("expected_total_goals_5", 0.0))
    return max(0.0, min(1.0, abs(expected - 2.5) / 2.5))


def _uncertainty(record: HistoricalRecord) -> float:
    base = 0.25
    if not record.has_odds:
        base += 0.35
    if len(record.sources) < 2:
        base += 0.2
    prior = float(record.features.get("prior_matches", 10.0))
    if prior < 5:
        base += 0.15
    return min(1.0, base)


def _dimension_coverage(profile: MatchSimilarityProfile) -> float:
    present = len(_ALWAYS_PRESENT) + sum(
        1 for name in _OPTIONAL if getattr(profile, name) is not None
    )
    return present / TOTAL_DIMENSIONS


def _profile_signature(profile: MatchSimilarityProfile) -> tuple:
    return (
        profile.competition,
        round(profile.elo_delta, 4),
        round(profile.home_form, 4),
        round(profile.away_form, 4),
        round(profile.draw_tendency, 4),
        (
            round(profile.market_pressure, 4)
            if profile.market_pressure is not None
            else None
        ),
        round(profile.volatility, 4),
        round(profile.uncertainty, 4),
        round(profile.home_attack_strength, 4),
        round(profile.away_attack_strength, 4),
        round(profile.home_defense_strength, 4),
        round(profile.away_defense_strength, 4),
        round(profile.line_movement, 4) if profile.line_movement is not None else None,
        round(profile.h2h_advantage, 4) if profile.h2h_advantage is not None else None,
        (
            round(profile.table_position_gap, 4)
            if profile.table_position_gap is not None else None
        ),
        round(profile.rest_advantage, 4) if profile.rest_advantage is not None else None,
    )


def _common(values: Iterable[str], sample_size: int) -> list[str]:
    if sample_size == 0:
        return []
    counts = Counter(values)
    threshold = max(1, int(sample_size * 0.4))
    return sorted(name for name, count in counts.items() if count >= threshold)
