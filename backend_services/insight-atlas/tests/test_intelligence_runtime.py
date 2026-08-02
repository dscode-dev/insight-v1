from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.intelligence.historical import HistoricalDataset, HistoricalRecord
from atlas.intelligence.orchestrator import (
    AtlasIntelligenceOrchestrator,
    AtlasRuntimeContext,
    RuntimeOdds,
)

START = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _dataset() -> HistoricalDataset:
    teams = ("santos", "flamengo", "palmeiras", "corinthians")
    records = []
    for index in range(80):
        home = teams[index % len(teams)]
        away = teams[(index + 1 + index // 4) % len(teams)]
        if home == away:
            away = teams[(teams.index(home) + 1) % len(teams)]
        label = ("HOME_WIN", "DRAW", "AWAY_WIN")[index % 3]
        home_score, away_score = {
            "HOME_WIN": (2, 1),
            "DRAW": (1, 1),
            "AWAY_WIN": (0, 1),
        }[label]
        records.append(
            HistoricalRecord(
                uid=f"runtime-{index}",
                competition="brasileirao_serie_a",
                season=str(2020 + index // 20),
                kickoff_at=START + timedelta(days=index * 7),
                home=home,
                away=away,
                home_score=home_score,
                away_score=away_score,
                label=label,
                sources=("espn", "football-data"),
                features={
                    "home_points_5": 0.55 + (index % 3) * 0.05,
                    "away_points_5": 0.45 + (index % 2) * 0.05,
                    "elo_difference": ((index % 5) - 2) / 10,
                    "draw_rate_mean_5": 0.3,
                    "expected_total_goals_5": 2.4,
                    "odds_available": 1.0,
                    "opening_home": 2.2,
                    "opening_draw": 3.2,
                    "opening_away": 3.5,
                    "closing_home": 2.1,
                    "closing_draw": 3.3,
                    "closing_away": 3.7,
                    "favorite_strength": 0.48,
                    "market_entropy": 0.9,
                    "prior_matches": 10.0,
                },
            )
        )
    return HistoricalDataset(records)


def _context() -> AtlasRuntimeContext:
    return AtlasRuntimeContext(
        competition="brasileirao_serie_a",
        home_team="santos",
        away_team="flamengo",
        odds=RuntimeOdds(
            opening_home=2.2,
            opening_draw=3.2,
            opening_away=3.5,
            current_home=2.0,
            current_draw=3.3,
            current_away=3.9,
            bookmaker="runtime-test",
        ),
    )


def test_orchestrator_executes_every_intelligence_engine() -> None:
    report = AtlasIntelligenceOrchestrator(_dataset()).execute(_context())

    assert report.signals
    assert report.evidence
    assert report.trends
    assert report.market is not None
    assert report.behaviors
    assert report.memory is not None
    assert report.similarity is not None
    assert report.uncertainty is not None
    assert report.reasoning is not None
    assert report.graph is not None
    assert report.confidence_explanation is not None
    assert report.uncertainty_explanation is not None
    assert "reasoning_engine" in report.runtime.completed_engines
    assert report.runtime.completed_engines == report.runtime.engine_order
    assert report.runtime.request_odds_used is True
    assert report.memory.retrieval_order[0].value == "head_to_head"


def test_runtime_report_is_deterministic_and_non_predictive() -> None:
    orchestrator = AtlasIntelligenceOrchestrator(_dataset())
    first = orchestrator.execute(_context()).model_dump(mode="json")
    second = orchestrator.execute(_context()).model_dump(mode="json")

    assert first == second
    assert not _contains_key(
        first,
        {"winner", "prediction", "pick", "bet", "predicted_score"},
    )


def test_runtime_memory_is_team_safe_and_same_competition() -> None:
    report = AtlasIntelligenceOrchestrator(_dataset()).execute(_context())
    pair = {"santos", "flamengo"}

    assert all(
        pair & {item.home, item.away}
        for item in report.memory.behavior_memory.matches
    )
    assert all(
        item.competition == "brasileirao_serie_a"
        for item in report.memory.generic_similarity
    )
    assert report.head_to_head.home_team == "santos"
    assert report.head_to_head.away_team == "flamengo"


def test_request_odds_change_market_runtime_not_historical_memory() -> None:
    orchestrator = AtlasIntelligenceOrchestrator(_dataset())
    first = orchestrator.execute(_context())
    changed = _context().model_copy(
        update={
            "odds": RuntimeOdds(
                opening_home=2.2,
                opening_draw=3.2,
                opening_away=3.5,
                current_home=2.6,
                current_draw=3.1,
                current_away=2.8,
            )
        }
    )
    second = orchestrator.execute(changed)

    assert first.market != second.market
    assert first.head_to_head == second.head_to_head
    assert first.home_team_memory == second.home_team_memory
    assert first.away_team_memory == second.away_team_memory


def test_reasoning_graph_links_every_behavior_to_evidence_signal_and_memory() -> None:
    report = AtlasIntelligenceOrchestrator(_dataset()).execute(_context())
    incoming = {}
    for edge in report.graph.edges:
        incoming.setdefault(edge.target_node_id, []).append(edge)

    for behavior in report.behaviors:
        node_id = f"behavior:{behavior.pattern_id}"
        edges = incoming[node_id]
        assert any(edge.source_node_id.startswith("evidence:") for edge in edges)
        assert any(edge.source_node_id.startswith("signal:") for edge in edges)
        assert any(edge.source_node_id.startswith("memory:") for edge in edges)
        assert behavior.type.value in report.reasoning.behavior_explanations


def test_reasoning_detects_market_pressure_disagreement_conflict() -> None:
    context = _context().model_copy(
        update={
            "odds": RuntimeOdds(
                opening_home=2.2,
                opening_draw=3.2,
                opening_away=3.5,
                current_home=1.3,
                current_draw=5.0,
                current_away=8.0,
            )
        }
    )
    report = AtlasIntelligenceOrchestrator(_dataset()).execute(context)

    assert any(
        "favorite pressure" in conflict.description.lower()
        for conflict in report.conflicts
    )
    assert any(
        edge.edge_type.value == "conflicts_with"
        for edge in report.graph.edges
    )


def test_confidence_and_uncertainty_reasoning_are_explicit() -> None:
    report = AtlasIntelligenceOrchestrator(_dataset()).execute(_context())

    assert report.confidence_explanation.level in {"low", "medium", "high"}
    assert report.confidence_explanation.positive_factors
    assert "no live match-state data" in report.uncertainty_explanation.reasons
    assert report.uncertainty_explanation.missing_inputs


def _contains_key(value, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            key.lower() in forbidden or _contains_key(child, forbidden)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(child, forbidden) for child in value)
    return False
