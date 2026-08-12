"""ML-D.3 football-intelligence feature schema.

All values are pre-match. Missing external context (notably odds) is represented
by neutral zero values plus an explicit availability feature.
"""

from __future__ import annotations

FEATURE_SCHEMA_VERSION_V2 = "feature_schema_v2"
OUTCOME_VERSION_V2 = "outcome_v2"

FEATURE_NAMES_OUTCOME_V2: list[str] = []

for side in ("home", "away"):
    for window in (3, 5, 10):
        FEATURE_NAMES_OUTCOME_V2.extend(
            [
                f"{side}_wins_{window}",
                f"{side}_draws_{window}",
                f"{side}_losses_{window}",
                f"{side}_points_{window}",
            ]
        )
    for window in (5, 10):
        FEATURE_NAMES_OUTCOME_V2.extend(
            [
                f"{side}_goals_for_{window}",
                f"{side}_goals_against_{window}",
                f"{side}_goal_difference_{window}",
            ]
        )

FEATURE_NAMES_OUTCOME_V2.extend(
    [
        "home_strength",
        "away_strength",
        "home_win_rate",
        "away_win_rate",
        "home_goal_rate",
        "away_goal_rate",
        "last_h2h_matches",
        "h2h_home_wins",
        "h2h_away_wins",
        "h2h_draws",
        "h2h_goal_difference",
        "home_league_position",
        "away_league_position",
        "home_league_points",
        "away_league_points",
        "home_league_goal_difference",
        "away_league_goal_difference",
        "home_recent_rank_change",
        "away_recent_rank_change",
        "home_rest_days",
        "away_rest_days",
        "home_advantage",
        "form_strength_gap",
        "goal_rate_gap",
        "draw_rate_mean_5",
        "draw_rate_gap_5",
        "expected_total_goals_5",
        "opening_home",
        "opening_draw",
        "opening_away",
        "closing_home",
        "closing_draw",
        "closing_away",
        "implied_home_probability",
        "implied_draw_probability",
        "implied_away_probability",
        "bookmaker_spread",
        "odds_available",
    ]
)


def outcome_v2_defaults() -> dict[str, float]:
    defaults = {name: 0.0 for name in FEATURE_NAMES_OUTCOME_V2}
    defaults.update(
        {
            "home_rest_days": 14.0 / 30.0,
            "away_rest_days": 14.0 / 30.0,
            "home_advantage": 1.0,
        }
    )
    return defaults

