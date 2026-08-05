"""Coverage for AtlasIntelligenceOrchestrator._runtime_query's new
strength/market merging (ATLAS-SIM-A) — the live query's `.features`
dict must carry the new signals when available, and degrade gracefully
(never fabricate) when they aren't."""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.intelligence.orchestrator import (
    AtlasIntelligenceOrchestrator,
    AtlasRuntimeContext,
    RuntimeOdds,
)
from atlas.strength.models import TeamStrengthFeatures

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _context(*, with_odds: bool = True) -> AtlasRuntimeContext:
    return AtlasRuntimeContext(
        competition="brasileirao_serie_a",
        home_team="santos",
        away_team="flamengo",
        odds=(
            RuntimeOdds(
                opening_home=2.5, opening_draw=3.2, opening_away=3.0,
                current_home=2.0, current_draw=3.3, current_away=3.9,
                bookmaker="runtime-test",
            )
            if with_odds else None
        ),
    )


def _strength() -> TeamStrengthFeatures:
    return TeamStrengthFeatures(
        elo_delta=0.35,
        home_attack_strength=0.7,
        away_attack_strength=0.4,
        home_defense_strength=0.6,
        away_defense_strength=0.5,
        h2h_advantage=0.5,
        table_position_gap=0.2,
        rest_advantage=-0.1,
    )


def test_runtime_query_merges_strength_features():
    record = AtlasIntelligenceOrchestrator._runtime_query(
        _context(with_odds=False), rows=[], as_of=START, strength=_strength(), market=None,
    )
    assert record.features["elo_difference"] == 0.35
    assert record.features["home_attack_strength"] == 0.7
    assert record.features["away_attack_strength"] == 0.4
    assert record.features["home_defense_strength"] == 0.6
    assert record.features["away_defense_strength"] == 0.5
    assert record.features["h2h_advantage"] == 0.5
    assert record.features["table_position_gap"] == 0.2
    assert record.features["rest_advantage"] == -0.1


def test_runtime_query_omits_none_strength_subfields():
    strength = TeamStrengthFeatures(
        elo_delta=0.0, home_attack_strength=0.5, away_attack_strength=0.5,
        home_defense_strength=0.5, away_defense_strength=0.5,
        h2h_advantage=None, table_position_gap=None, rest_advantage=None,
    )
    record = AtlasIntelligenceOrchestrator._runtime_query(
        _context(with_odds=False), rows=[], as_of=START, strength=strength, market=None,
    )
    assert "h2h_advantage" not in record.features
    assert "table_position_gap" not in record.features
    assert "rest_advantage" not in record.features


def test_runtime_query_without_strength_leaves_original_behavior():
    record = AtlasIntelligenceOrchestrator._runtime_query(
        _context(with_odds=False), rows=[], as_of=START, strength=None, market=None,
    )
    assert "home_attack_strength" not in record.features
    assert record.features["elo_difference"] == 0.0  # unchanged fallback


def test_runtime_query_computes_line_movement_from_request_odds():
    record = AtlasIntelligenceOrchestrator._runtime_query(
        _context(with_odds=True), rows=[], as_of=START, strength=None, market=None,
    )
    # opening_home=2.5 (implied ~0.40) -> current_home=2.0 (implied ~0.50):
    # the market moved TOWARD the home side between open and close.
    assert record.features["line_movement"] > 0
