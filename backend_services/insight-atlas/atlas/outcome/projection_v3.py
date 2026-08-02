"""Leakage-safe market, ELO, and team-strength projection."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from atlas.outcome.projection import HistoricalMatch
from atlas.outcome.projection_v2 import HistoricalProjectionV2, ProjectedRowV2
from atlas.outcome.schema_v3 import FEATURE_NAMES_OUTCOME_V3, outcome_v3_defaults

COMPETITION_WEIGHTS = {
    "champions_league": 1.00,
    "premier_league": 0.96,
    "la_liga": 0.94,
    "serie_a": 0.92,
    "bundesliga": 0.90,
    "ligue_1": 0.86,
    "brasileirao_serie_a": 0.82,
}


class HistoricalProjectionV3(HistoricalProjectionV2):
    def __init__(
        self,
        odds_by_uid: dict[str, dict[str, dict[str, float]]] | None = None,
    ) -> None:
        super().__init__(odds_by_uid)
        self._elo: dict[str, float] = defaultdict(lambda: 1500.0)
        self._venue_elo: dict[tuple[str, str], float] = defaultdict(lambda: 1500.0)
        self._competition_goals: dict[tuple[str, str], list[int]] = defaultdict(list)

    def _features(self, match: HistoricalMatch, standings):  # type: ignore[no-untyped-def]
        features = super()._features(match, standings)
        features.update(self._market_features(features))
        features.update(self._strength_features(match))
        return features

    def _market_features(self, features: dict[str, float]) -> dict[str, float]:
        if not features.get("odds_available"):
            return {}
        probabilities = np.asarray(
            [
                features["implied_home_probability"],
                features["implied_draw_probability"],
                features["implied_away_probability"],
            ],
            dtype=float,
        )
        order = np.argsort(probabilities)
        favorite = int(order[-1])
        entropy = -sum(value * math.log(value + 1e-12) for value in probabilities)
        return {
            "implied_home": float(probabilities[0]),
            "implied_draw": float(probabilities[1]),
            "implied_away": float(probabilities[2]),
            "market_favorite": favorite / 2.0,
            "favorite_strength": float(probabilities[favorite]),
            "market_gap": float(probabilities[order[-1]] - probabilities[order[-2]]),
            "market_entropy": float(entropy / math.log(3)),
        }

    def _strength_features(self, match: HistoricalMatch) -> dict[str, float]:
        home_elo = self._elo[match.home]
        away_elo = self._elo[match.away]
        home_history = self._history[match.home][-10:]
        away_history = self._history[match.away][-10:]
        competition_goals = self._competition_goals[(match.competition, match.season)]
        league_goal_rate = (
            sum(competition_goals) / len(competition_goals)
            if competition_goals
            else 1.35
        )

        def attack(rows) -> float:  # type: ignore[no-untyped-def]
            return (
                sum(row.goals_for for row in rows) / max(len(rows), 1)
            ) / max(league_goal_rate, 0.25)

        def defense(rows) -> float:  # type: ignore[no-untyped-def]
            conceded = sum(row.goals_against for row in rows) / max(len(rows), 1)
            return league_goal_rate / max(conceded, 0.25)

        participants = {
            team
            for old in self._competition_matches[(match.competition, match.season)]
            for team in (old.home, old.away)
        }
        league_elo = (
            sum(self._elo[team] for team in participants) / len(participants)
            if participants
            else 1500.0
        )
        return {
            "home_elo_rating": home_elo / 3000.0,
            "away_elo_rating": away_elo / 3000.0,
            "elo_difference": (home_elo - away_elo) / 400.0,
            "home_attack_strength": attack(home_history),
            "away_attack_strength": attack(away_history),
            "home_defense_strength": defense(home_history),
            "away_defense_strength": defense(away_history),
            "home_rating": self._venue_elo[(match.home, "home")] / 3000.0,
            "away_rating": self._venue_elo[(match.away, "away")] / 3000.0,
            "league_strength": league_elo / 3000.0,
            "competition_weight": COMPETITION_WEIGHTS.get(match.competition, 0.75),
        }

    def _record(self, match: HistoricalMatch) -> None:
        home_elo = self._elo[match.home]
        away_elo = self._elo[match.away]
        expected_home = 1.0 / (1.0 + 10 ** ((away_elo - (home_elo + 65.0)) / 400.0))
        actual_home = (
            1.0 if match.home_score > match.away_score
            else 0.5 if match.home_score == match.away_score
            else 0.0
        )
        margin = abs(match.home_score - match.away_score)
        k = 20.0 * (1.0 + min(margin, 4) * 0.15)
        delta = k * (actual_home - expected_home)
        self._elo[match.home] = home_elo + delta
        self._elo[match.away] = away_elo - delta

        home_venue = self._venue_elo[(match.home, "home")]
        away_venue = self._venue_elo[(match.away, "away")]
        expected_venue = 1.0 / (1.0 + 10 ** ((away_venue - home_venue) / 400.0))
        venue_delta = 16.0 * (actual_home - expected_venue)
        self._venue_elo[(match.home, "home")] = home_venue + venue_delta
        self._venue_elo[(match.away, "away")] = away_venue - venue_delta
        self._competition_goals[(match.competition, match.season)].extend(
            [match.home_score, match.away_score]
        )
        super()._record(match)


def vector_v3(row: ProjectedRowV2) -> list[float]:
    values = outcome_v3_defaults()
    values.update(
        {key: float(value) for key, value in row.features.items() if key in values}
    )
    return [values[name] for name in FEATURE_NAMES_OUTCOME_V3]

