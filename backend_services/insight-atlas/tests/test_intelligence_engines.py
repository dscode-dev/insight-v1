from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from atlas.intelligence import AtlasIntelligenceReport
from atlas.intelligence.historical import (
    HistoricalDataset,
    HistoricalRecord,
    HistoricalScope,
)
from atlas.intelligence.report_builder import HistoricalIntelligenceReportBuilder
from atlas.intelligence.similarity_engine import (
    HistoricalMemory,
    profile_from_record,
)
from atlas.memory import HierarchicalMemoryRetrievalEngine, MemoryLayer

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _records(*, odds: bool = True, competition: str = "premier_league"):
    rows = []
    labels = ["HOME_WIN", "DRAW", "AWAY_WIN", "DRAW", "HOME_WIN"]
    for index in range(30):
        label = labels[index % len(labels)]
        home_score, away_score = {
            "HOME_WIN": (2, 1),
            "DRAW": (1, 1),
            "AWAY_WIN": (0, 2),
        }[label]
        features = {
            "home_points_5": 0.55 + (index % 4) * 0.05,
            "away_points_5": 0.45,
            "form_strength_gap": 0.15,
            "home_goals_against_5": 1.0,
            "away_goals_against_5": 1.3,
            "favorite_strength": 0.62,
            "bookmaker_spread": 0.18,
            "odds_available": 1.0 if odds else 0.0,
        }
        if odds:
            features.update(
                {
                    "opening_home": 2.0,
                    "opening_draw": 3.4,
                    "opening_away": 3.8,
                    "closing_home": 1.9 - (index % 3) * 0.02,
                    "closing_draw": 3.5,
                    "closing_away": 4.0,
                }
            )
        rows.append(
            HistoricalRecord(
                uid=f"match-{index}",
                competition=competition,
                season="2023-2024",
                kickoff_at=START + timedelta(days=index),
                home=f"home-{index}",
                away=f"away-{index}",
                home_score=home_score,
                away_score=away_score,
                label=label,
                sources=("espn", "football-data") if odds else ("espn",),
                features=features,
            )
        )
    return rows


def test_builder_produces_canonical_intelligence_without_prediction() -> None:
    report = HistoricalIntelligenceReportBuilder(
        HistoricalDataset(_records())
    ).build(HistoricalScope("premier_league", year=2024))

    assert isinstance(report, AtlasIntelligenceReport)
    assert report.market is not None
    assert report.regime is not None
    assert report.signals
    assert report.trends
    assert report.similarity is not None
    assert report.similarity.similar_matches
    assert report.similarity.evidence
    assert report.behaviors
    assert report.patterns == [item.type.value for item in report.behaviors]
    assert all(pattern.evidence for pattern in report.behaviors)
    assert all(signal.evidence for signal in report.signals)
    names = {signal.signal_name for signal in report.signals}
    assert {
        "home_form",
        "away_form",
        "momentum",
        "streak",
        "favorite_pressure",
        "market_consensus",
        "market_disagreement",
        "competition_volatility",
        "draw_tendency",
        "scoring_tendency",
        "defensive_instability",
        "goal_distribution",
    } <= names
    body = report.model_dump(mode="json")
    assert not _contains_key(
        body, {"winner", "prediction", "pick", "bet", "predicted_score"}
    )


def test_missing_market_is_explicit_not_fabricated() -> None:
    report = HistoricalIntelligenceReportBuilder(
        HistoricalDataset(_records(odds=False, competition="libertadores"))
    ).build(HistoricalScope("libertadores", year=2024))

    assert report.market is None
    assert "market odds" in report.uncertainty.missing_signals
    assert report.uncertainty.low_coverage is True
    assert not any(
        signal.signal_name.startswith("market_")
        or signal.signal_name == "favorite_pressure"
        for signal in report.signals
    )


def test_report_is_deterministic_for_same_scope() -> None:
    builder = HistoricalIntelligenceReportBuilder(HistoricalDataset(_records()))
    first = builder.build(HistoricalScope("premier_league", year=2024))
    second = builder.build(HistoricalScope("premier_league", year=2024))
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_memory_uses_only_prior_matches_in_same_competition() -> None:
    records = _records()
    future = replace(
        records[-1],
        uid="future",
        kickoff_at=records[-1].kickoff_at + timedelta(days=10),
    )
    continental = replace(records[0], uid="continental", competition="libertadores")
    other_league = replace(records[1], uid="other-league", competition="la_liga")
    query = profile_from_record(records[-1])
    hits = HistoricalMemory(
        HistoricalDataset([*records, future, continental, other_league])
    ).retrieve_similar_contexts(query)
    ids = {hit.record.uid for hit in hits}
    assert "future" not in ids
    assert "continental" not in ids
    assert "other-league" not in ids
    assert all(hit.record.kickoff_at < query.kickoff_at for hit in hits)


def test_similarity_is_threshold_based_not_fixed_top_k() -> None:
    records = _records()
    query_record = replace(
        records[-1],
        features={**records[-1].features, "home_points_5": 0.1},
    )
    query = profile_from_record(query_record)
    memory = HistoricalMemory(HistoricalDataset(records))
    loose = memory.retrieve_similar_contexts(query, minimum_score=0.5)
    strict = memory.retrieve_similar_contexts(query, minimum_score=0.999)
    assert len(loose) > len(strict)
    assert len(loose) != 25


def test_behavior_patterns_have_history_confidence_and_uncertainty() -> None:
    report = HistoricalIntelligenceReportBuilder(
        HistoricalDataset(_records())
    ).build(HistoricalScope("premier_league", year=2024))
    types = {pattern.type.value for pattern in report.behaviors}
    assert {"draw_tendency", "favorite_pressure", "stable"} <= types
    for pattern in report.behaviors:
        assert pattern.history.sample_size == report.similarity.actual_neighbor_count
        assert pattern.evidence
        assert 0 <= pattern.confidence <= 1
        assert 0 <= pattern.uncertainty <= 1


def test_hierarchical_memory_requires_team_participation_before_analogues() -> None:
    records = _records()
    query = replace(records[-1], home="santos", away="flamengo")
    prior_h2h = replace(
        records[0], uid="h2h", home="flamengo", away="santos"
    )
    prior_home = replace(
        records[1], uid="santos-history", home="santos", away="corinthians"
    )
    prior_away = replace(
        records[2], uid="flamengo-history", home="palmeiras", away="flamengo"
    )
    memory = HierarchicalMemoryRetrievalEngine(
        HistoricalDataset([*records[:-1], prior_h2h, prior_home, prior_away, query])
    ).retrieve(query, minimum_similarity=0.5)

    assert memory.retrieval_order == list(MemoryLayer)
    assert memory.head_to_head.matches == 1
    assert memory.home_team_memory.team == "santos"
    assert memory.away_team_memory.team == "flamengo"
    assert memory.home_team_memory.matches == 2
    assert memory.away_team_memory.matches == 2
    assert all(
        "santos" in {item.home, item.away}
        or "flamengo" in {item.home, item.away}
        for item in memory.behavior_memory.matches
    )
    assert all(
        item.competition == query.competition
        for item in memory.generic_similarity
    )


def test_hierarchical_memory_is_strictly_prior_and_same_competition() -> None:
    records = _records()
    query = replace(records[-1], home="santos", away="flamengo")
    future = replace(
        records[-1],
        uid="future-santos",
        home="santos",
        away="flamengo",
        kickoff_at=query.kickoff_at + timedelta(days=1),
    )
    other_competition = replace(
        records[0],
        uid="other-comp",
        home="santos",
        away="flamengo",
        competition="libertadores",
    )
    memory = HierarchicalMemoryRetrievalEngine(
        HistoricalDataset([*records[:-1], query, future, other_competition])
    ).retrieve(query, minimum_similarity=0.5)

    assert memory.head_to_head.matches == 0
    assert memory.home_team_memory.matches == 0
    assert memory.away_team_memory.matches == 0
    assert all(
        item.kickoff_at < query.kickoff_at
        for item in memory.generic_similarity
    )


def test_report_exposes_hierarchical_memory_sections() -> None:
    records = _records()
    records[-1] = replace(records[-1], home="santos", away="flamengo")
    records[-2] = replace(records[-2], home="flamengo", away="santos")
    report = HistoricalIntelligenceReportBuilder(
        HistoricalDataset(records)
    ).build(
        HistoricalScope("premier_league", year=2024),
        home_team="santos",
        away_team="flamengo",
    )

    assert report.head_to_head.matches == 1
    assert report.home_team_memory.team == "santos"
    assert report.away_team_memory.team == "flamengo"
    assert report.memory_confidence.overall >= 0
    assert report.memory.retrieval_order[0] == MemoryLayer.head_to_head


def _contains_key(value, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            key.lower() in forbidden or _contains_key(child, forbidden)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(child, forbidden) for child in value)
    return False
