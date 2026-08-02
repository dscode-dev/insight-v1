"""Deterministic 32-dimensional football-context embeddings."""

from __future__ import annotations

import math

from atlas.intelligence.contracts import (
    AtlasIntelligenceReport,
    RegimeType,
)
from atlas.intelligence.historical import HistoricalRecord, stable_id
from atlas.intelligence.similarity_engine import profile_from_record
from atlas.vector_memory.contracts import MemoryEmbedding

_REGIME_INDEX = {
    RegimeType.league: 0,
    RegimeType.continental: 1,
    RegimeType.international: 2,
    RegimeType.knockout: 3,
    RegimeType.high_volatility: 3,
    RegimeType.low_information: 3,
}

_BEHAVIOR_INDEX = {
    "low_scoring": 12,
    "high_scoring": 13,
    "draw_tendency": 14,
    "draw_resistance": 15,
    "favorite_pressure": 16,
    "stable": 17,
    "volatile": 18,
    "market_disagreement": 19,
}

_TREND_INDEX = {
    "draw_trend": 20,
    "goal_trend": 21,
    "favorite_trend": 22,
    "market_trend": 23,
    "volatility_trend": 24,
}

_SIGNAL_INDEX = {
    "home_form": 25,
    "away_form": 26,
    "momentum": 27,
    "scoring_tendency": 28,
    "competition_volatility": 29,
    "market_disagreement": 30,
}


class DeterministicEmbeddingEncoder:
    def from_record(self, record: HistoricalRecord) -> MemoryEmbedding:
        profile = profile_from_record(record)
        behaviors = _record_behaviors(profile)
        values = [0.0] * 32
        values[_REGIME_INDEX[profile.regime]] = 1.0
        values[4] = (profile.elo_delta + 1.0) / 2.0
        values[5] = profile.home_form
        values[6] = profile.away_form
        values[7] = profile.draw_tendency
        values[8] = profile.volatility
        values[9] = profile.uncertainty
        values[10] = profile.market_pressure or 0.0
        values[11] = 1.0 if profile.market_available else 0.0
        _mark(values, behaviors, _BEHAVIOR_INDEX)
        _mark(values, profile.trends, _TREND_INDEX)
        values[25] = profile.home_form
        values[26] = profile.away_form
        values[27] = abs(profile.home_form - profile.away_form)
        values[28] = min(
            1.0,
            float(record.features.get("expected_total_goals_5", 0.0)) / 4.0,
        )
        values[29] = profile.volatility
        values[30] = min(
            1.0, float(record.features.get("bookmaker_spread", 0.0))
        )
        values[31] = 1.0
        return MemoryEmbedding(
            vector_id=stable_id("vector-memory", record.uid),
            source_match_id=record.uid,
            competition=record.competition,
            regime=profile.regime,
            home_team=record.home,
            away_team=record.away,
            behavior=sorted(behaviors),
            trends=sorted(profile.trends),
            signals=sorted(profile.signals),
            market_available=profile.market_available,
            uncertainty=profile.uncertainty,
            embedding=_normalise(values),
            created_at=record.kickoff_at,
        )

    def from_report(self, report: AtlasIntelligenceReport) -> MemoryEmbedding:
        if report.regime is None or report.memory is None:
            raise ValueError("report lacks regime or hierarchical memory")
        values = [0.0] * 32
        values[_REGIME_INDEX[report.regime.regime_type]] = 1.0
        signal = {item.signal_name: item for item in report.signals}
        behavior_names = {item.type.value for item in report.behaviors}
        trend_names = {item.trend_type for item in report.trends}
        values[4] = 0.5
        values[5] = signal.get("home_form").strength if signal.get("home_form") else 0.0
        values[6] = signal.get("away_form").strength if signal.get("away_form") else 0.0
        values[7] = (
            signal.get("draw_tendency").strength
            if signal.get("draw_tendency")
            else report.memory.competition_memory.draw_rate
        )
        values[8] = (
            signal.get("competition_volatility").strength
            if signal.get("competition_volatility")
            else report.memory.competition_memory.volatility
        )
        values[9] = report.uncertainty.uncertainty_score
        values[10] = report.market.favorite_pressure if report.market else 0.0
        values[11] = 1.0 if report.market else 0.0
        _mark(values, behavior_names, _BEHAVIOR_INDEX)
        _mark(values, trend_names, _TREND_INDEX)
        for name, index in _SIGNAL_INDEX.items():
            values[index] = signal[name].strength if name in signal else 0.0
        values[31] = 1.0
        memory = report.memory
        return MemoryEmbedding(
            vector_id=stable_id(
                "runtime-vector",
                report.report_id,
                report.as_of.isoformat(),
            ),
            source_match_id=str(report.match_id or report.report_id),
            competition=memory.competition,
            regime=report.regime.regime_type,
            home_team=memory.home_team,
            away_team=memory.away_team,
            behavior=sorted(behavior_names),
            trends=sorted(trend_names),
            signals=sorted(signal),
            market_available=report.market is not None,
            uncertainty=report.uncertainty.uncertainty_score,
            embedding=_normalise(values),
            created_at=report.as_of,
        )


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def _record_behaviors(profile) -> set[str]:
    result = set()
    result.add(
        "draw_tendency" if profile.draw_tendency >= 0.28 else "draw_resistance"
    )
    result.add("volatile" if profile.volatility >= 0.65 else "stable")
    if profile.market_pressure is not None and profile.market_pressure >= 0.6:
        result.add("favorite_pressure")
    return result


def _mark(values, names, mapping) -> None:
    for name in names:
        if name in mapping:
            values[mapping[name]] = 1.0


def _normalise(values: list[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        return tuple(values)
    return tuple(round(value / norm, 8) for value in values)
