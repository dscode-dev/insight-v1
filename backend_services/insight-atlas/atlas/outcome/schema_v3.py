"""ML-D.4 market and team-strength feature schema."""

from __future__ import annotations

from atlas.outcome.schema_v2 import FEATURE_NAMES_OUTCOME_V2, outcome_v2_defaults

FEATURE_SCHEMA_VERSION_V3 = "feature_schema_v3"
OUTCOME_VERSION_V3 = "outcome_v3"

FEATURE_NAMES_OUTCOME_V3 = [
    *FEATURE_NAMES_OUTCOME_V2,
    "implied_home",
    "implied_draw",
    "implied_away",
    "market_favorite",
    "favorite_strength",
    "market_gap",
    "market_entropy",
    "home_elo_rating",
    "away_elo_rating",
    "elo_difference",
    "home_attack_strength",
    "away_attack_strength",
    "home_defense_strength",
    "away_defense_strength",
    "home_rating",
    "away_rating",
    "league_strength",
    "competition_weight",
]


def outcome_v3_defaults() -> dict[str, float]:
    values = outcome_v2_defaults()
    values.update({name: 0.0 for name in FEATURE_NAMES_OUTCOME_V3 if name not in values})
    values.update(
        {
            "home_elo_rating": 0.5,
            "away_elo_rating": 0.5,
            "home_rating": 0.5,
            "away_rating": 0.5,
            "league_strength": 0.5,
            "competition_weight": 0.5,
        }
    )
    return values

