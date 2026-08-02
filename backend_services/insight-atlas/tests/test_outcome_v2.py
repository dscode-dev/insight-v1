from datetime import datetime, timezone

import pytest

from atlas.outcome.projection import HistoricalMatch
from atlas.outcome.projection_v2 import HistoricalProjectionV2
from atlas.outcome.projection_v3 import HistoricalProjectionV3, vector_v3
from atlas.outcome.schema_v2 import FEATURE_NAMES_OUTCOME_V2
from atlas.outcome.schema_v3 import FEATURE_NAMES_OUTCOME_V3


def match(
    uid: str,
    day: int,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
) -> HistoricalMatch:
    return HistoricalMatch(
        uid=uid,
        kickoff_at=datetime(2024, 1, day, tzinfo=timezone.utc),
        competition="league",
        season="2024",
        home=home,
        away=away,
        home_score=home_score,
        away_score=away_score,
    )


def test_feature_schema_v2_is_unique() -> None:
    assert len(FEATURE_NAMES_OUTCOME_V2) == 74
    assert len(set(FEATURE_NAMES_OUTCOME_V2)) == 74


def test_projection_v2_uses_only_prior_matches() -> None:
    rows = HistoricalProjectionV2().project(
        [
            match("one", 1, "a", "b", 2, 0),
            match("two", 2, "a", "c", 1, 1),
        ]
    )
    assert rows[0].features["home_wins_3"] == 0
    assert rows[1].features["home_wins_3"] == 1
    assert rows[1].features["home_points_3"] == 1
    assert rows[1].features["home_goals_for_5"] == 2


def test_same_timestamp_batch_cannot_leak() -> None:
    kickoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = HistoricalProjectionV2().project(
        [
            HistoricalMatch("one", kickoff, "league", "2024", "a", "b", 2, 0),
            HistoricalMatch("two", kickoff, "league", "2024", "a", "c", 4, 0),
        ]
    )
    assert rows[0].features["home_wins_3"] == 0
    assert rows[1].features["home_wins_3"] == 0


def test_h2h_is_oriented_to_current_home_team() -> None:
    rows = HistoricalProjectionV2().project(
        [
            match("one", 1, "a", "b", 2, 0),
            match("two", 2, "b", "a", 0, 1),
        ]
    )
    assert rows[1].features["last_h2h_matches"] == pytest.approx(0.1)
    assert rows[1].features["h2h_away_wins"] == 1
    assert rows[1].features["h2h_goal_difference"] == -2


def test_odds_features_are_normalized_when_available() -> None:
    projection = HistoricalProjectionV2(
        {
            "one": {
                "opening": {"home": 2.0, "draw": 3.0, "away": 4.0},
                "closing": {"home": 1.8, "draw": 3.2, "away": 4.5},
            }
        }
    )
    row = projection.project([match("one", 1, "a", "b", 1, 0)])[0]
    assert row.features["odds_available"] == 1
    assert row.features["opening_home"] == 2.0
    assert sum(
        row.features[key]
        for key in (
            "implied_home_probability",
            "implied_draw_probability",
            "implied_away_probability",
        )
    ) == pytest.approx(1.0)


def test_feature_schema_v3_market_and_elo_are_leakage_safe() -> None:
    projection = HistoricalProjectionV3(
        {
            "one": {
                "opening": {"home": 2.0, "draw": 3.0, "away": 4.0},
                "closing": {"home": 1.8, "draw": 3.2, "away": 4.5},
            }
        }
    )
    rows = projection.project(
        [
            match("one", 1, "a", "b", 2, 0),
            match("two", 2, "a", "b", 0, 1),
        ]
    )
    assert len(FEATURE_NAMES_OUTCOME_V3) == 92
    assert len(vector_v3(rows[0])) == 92
    assert rows[0].features["home_elo_rating"] == pytest.approx(0.5)
    assert rows[0].features["market_gap"] > 0
    assert rows[1].features["home_elo_rating"] > 0.5
