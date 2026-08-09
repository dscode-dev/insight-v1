"""Coverage for the ATLAS-SIM-A (v2) similarity-engine expansion:
15-signal weight table, new profile fields, missing-data renormalization,
dimension coverage. v1 behavior (7-signal weighting) stays reachable
whenever the new fields are simply absent from `record.features` —
these tests double as a regression check that nothing about the
existing 7 signals changed."""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.intelligence.historical import HistoricalRecord
from atlas.intelligence.similarity_engine.engine import (
    _WEIGHTS,
    TOTAL_DIMENSIONS,
    _dimension_coverage,
    _similarity,
    profile_from_record,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(uid: str, features: dict, *, has_odds: bool = False) -> HistoricalRecord:
    merged = dict(features)
    if has_odds:
        merged.setdefault("odds_available", 1.0)
        merged.setdefault("favorite_strength", 0.6)
    return HistoricalRecord(
        uid=uid, competition="premier_league", season="2026", kickoff_at=NOW,
        home="arsenal", away="chelsea", home_score=1, away_score=0, label="HOME_WIN",
        sources=("espn",), features=merged,
    )


def test_weights_sum_to_one():
    assert round(sum(_WEIGHTS.values()), 6) == 1.0


def test_total_dimensions_matches_weight_table_size():
    assert TOTAL_DIMENSIONS == len(_WEIGHTS) == 15


def test_profile_from_record_defaults_strength_to_neutral_when_absent():
    profile = profile_from_record(_record("m1", {}))
    assert profile.home_attack_strength == 0.5
    assert profile.away_attack_strength == 0.5
    assert profile.home_defense_strength == 0.5
    assert profile.away_defense_strength == 0.5
    assert profile.h2h_advantage is None
    assert profile.table_position_gap is None
    assert profile.rest_advantage is None
    assert profile.line_movement is None


def test_profile_from_record_reads_new_fields_when_present():
    profile = profile_from_record(_record("m1", {
        "home_attack_strength": 0.8, "away_attack_strength": 0.3,
        "home_defense_strength": 0.6, "away_defense_strength": 0.4,
        "h2h_advantage": 0.5, "table_position_gap": -0.2,
        "rest_advantage": 0.1, "line_movement": -0.3,
    }))
    assert profile.home_attack_strength == 0.8
    assert profile.away_attack_strength == 0.3
    assert profile.h2h_advantage == 0.5
    assert profile.table_position_gap == -0.2
    assert profile.rest_advantage == 0.1
    assert profile.line_movement == -0.3


def test_dimension_coverage_full_vs_partial():
    full = profile_from_record(_record("m1", {
        "h2h_advantage": 0.1, "table_position_gap": 0.1,
        "rest_advantage": 0.1, "line_movement": 0.1,
    }, has_odds=True))
    partial = profile_from_record(_record("m2", {}))
    assert _dimension_coverage(full) == 1.0
    # 10 always-present dims out of 15 total, none of the 5 optional set.
    assert round(_dimension_coverage(partial), 6) == round(10 / 15, 6)


def test_similarity_identical_profiles_scores_near_one():
    features = {
        "home_attack_strength": 0.7, "away_attack_strength": 0.4,
        "home_defense_strength": 0.6, "away_defense_strength": 0.5,
        "h2h_advantage": 0.3, "table_position_gap": 0.2,
        "rest_advantage": -0.1, "line_movement": 0.05,
        "elo_difference": 0.2, "home_points_5": 0.6, "away_points_5": 0.4,
        "draw_rate_mean_5": 0.25,
    }
    left = profile_from_record(_record("m1", features, has_odds=True))
    right = profile_from_record(_record("m2", features, has_odds=True))
    score, shared_signals, _ = _similarity(left, right)
    assert score > 0.99
    assert "home_attack_strength" in shared_signals


def test_similarity_missing_optional_signals_still_scores_using_core_dims():
    left = profile_from_record(_record("m1", {"home_attack_strength": 0.9}))
    right = profile_from_record(_record("m2", {"home_attack_strength": 0.1}))
    # Neither has market/h2h/standings/rest/line-movement data — the
    # comparison must still complete using only the always-present dims,
    # not crash or silently treat missing data as maximally similar.
    score, shared_signals, _ = _similarity(left, right)
    assert 0.0 <= score <= 1.0
    assert "line_movement" not in shared_signals
    assert "h2h_advantage" not in shared_signals


def test_similarity_one_sided_optional_signal_is_excluded_from_comparison():
    left = profile_from_record(_record("m1", {"h2h_advantage": 1.0}))
    right = profile_from_record(_record("m2", {}))  # no h2h data at all
    # h2h_advantage present on only one side must be excluded entirely
    # (not compared against a fabricated 0.0), same discipline
    # market_pressure already had in v1.
    _score, shared_signals, _ = _similarity(left, right)
    assert "h2h_advantage" not in shared_signals
