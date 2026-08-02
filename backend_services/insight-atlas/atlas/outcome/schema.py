"""Outcome-learning feature schema (outcome_v1).

SEPARATE from the live `atlas.features` schema (feature_schema_version=2). These
features are PRE-MATCH context derived from prior results only — never live
in-match signals. Vectors are positional in FEATURE_NAMES_OUTCOME order.
"""

from __future__ import annotations

OUTCOME_SCHEMA_VERSION = "outcome_v1"

# Positional feature order — the authoritative column order for outcome vectors.
FEATURE_NAMES_OUTCOME: list[str] = [
    "home_form_pts5",    # avg points/match, home team's prior <=5 matches
    "away_form_pts5",    # avg points/match, away team's prior <=5 matches
    "home_gf5",          # avg goals-for, home prior 5
    "home_ga5",          # avg goals-against, home prior 5
    "away_gf5",          # avg goals-for, away prior 5
    "away_ga5",          # avg goals-against, away prior 5
    "home_gd5",          # home_gf5 - home_ga5 (recent goal difference)
    "away_gd5",          # away_gf5 - away_ga5
    "h2h_home_winrate",  # home win rate in prior head-to-head meetings
    "home_rest_days",    # days since home team's prior match (norm /30)
    "away_rest_days",    # days since away team's prior match (norm /30)
    "home_advantage",    # 1.0 normal venue, 0.0 neutral (e.g. World Cup)
]

# 3-class result label. Optional goal-band labels live in labels.py.
OUTCOME_LABELS: list[str] = ["HOME_WIN", "DRAW", "AWAY_WIN"]
OUTCOME_LABEL_TO_ID: dict[str, int] = {l: i for i, l in enumerate(OUTCOME_LABELS)}

# Cold-start defaults (used when a team has no prior matches in-window).
_DEFAULTS: dict[str, float] = {
    "home_form_pts5": 1.0,
    "away_form_pts5": 1.0,
    "home_gf5": 1.2,
    "home_ga5": 1.2,
    "away_gf5": 1.2,
    "away_ga5": 1.2,
    "home_gd5": 0.0,
    "away_gd5": 0.0,
    "h2h_home_winrate": 0.5,
    "home_rest_days": 14.0 / 30.0,
    "away_rest_days": 14.0 / 30.0,
    "home_advantage": 1.0,
}


def outcome_defaults() -> dict[str, float]:
    return dict(_DEFAULTS)
