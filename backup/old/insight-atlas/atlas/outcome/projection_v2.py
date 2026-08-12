"""Leakage-safe ML-D.3 football feature projection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Iterable

import numpy as np

from atlas.outcome.labels import result_label
from atlas.outcome.projection import HistoricalMatch
from atlas.outcome.schema_v2 import FEATURE_NAMES_OUTCOME_V2, outcome_v2_defaults


@dataclass(frozen=True)
class ProjectedRowV2:
    uid: str
    kickoff_at: datetime
    competition: str
    season: str
    features: dict[str, float]
    label: str
    prior_matches: int

    def vector(self) -> list[float]:
        values = outcome_v2_defaults()
        values.update(
            {key: float(value) for key, value in self.features.items() if key in values}
        )
        return [values[name] for name in FEATURE_NAMES_OUTCOME_V2]


@dataclass(frozen=True)
class _TeamResult:
    kickoff_at: datetime
    goals_for: int
    goals_against: int
    points: int
    venue: str


class HistoricalProjectionV2:
    """Projects timestamp batches before recording any match in that batch."""

    def __init__(
        self,
        odds_by_uid: dict[str, dict[str, dict[str, float]]] | None = None,
    ) -> None:
        self._history: dict[str, list[_TeamResult]] = defaultdict(list)
        self._h2h: dict[tuple[str, str], list[HistoricalMatch]] = defaultdict(list)
        self._competition_matches: dict[tuple[str, str], list[HistoricalMatch]] = (
            defaultdict(list)
        )
        self._last_positions: dict[tuple[str, str, str], int] = {}
        self._odds_by_uid = odds_by_uid or {}

    def project(self, matches: Iterable[HistoricalMatch]) -> list[ProjectedRowV2]:
        ordered = sorted(matches, key=lambda match: (match.kickoff_at, match.uid))
        rows: list[ProjectedRowV2] = []
        for _, batch_iter in groupby(ordered, key=lambda match: match.kickoff_at):
            batch = list(batch_iter)
            standings_cache: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
            for match in batch:
                comp_key = (match.competition, match.season)
                standings = standings_cache.setdefault(
                    comp_key, self._standings(*comp_key)
                )
                features = self._features(match, standings)
                rows.append(
                    ProjectedRowV2(
                        uid=match.uid,
                        kickoff_at=match.kickoff_at,
                        competition=match.competition,
                        season=match.season,
                        features=features,
                        label=result_label(match.home_score, match.away_score),
                        prior_matches=len(self._history[match.home])
                        + len(self._history[match.away]),
                    )
                )
            for match in batch:
                self._record(match)
        return rows

    def _features(
        self, match: HistoricalMatch, standings: dict[str, dict[str, float]]
    ) -> dict[str, float]:
        features: dict[str, float] = {}
        home_windows = self._form_features(match.home)
        away_windows = self._form_features(match.away)
        features.update({f"home_{key}": value for key, value in home_windows.items()})
        features.update({f"away_{key}": value for key, value in away_windows.items()})
        features.update(self._venue_features(match))
        features.update(self._h2h_features(match))
        features.update(self._competition_features(match, standings))

        home_hist = self._history[match.home]
        away_hist = self._history[match.away]
        features["home_rest_days"] = self._rest(home_hist, match.kickoff_at)
        features["away_rest_days"] = self._rest(away_hist, match.kickoff_at)
        features["home_advantage"] = 0.0 if match.neutral else 1.0
        features["form_strength_gap"] = (
            features["home_points_5"] - features["away_points_5"]
        )
        features["goal_rate_gap"] = (
            features["home_goals_for_5"] - features["away_goals_for_5"]
        )
        features["draw_rate_mean_5"] = (
            features["home_draws_5"] + features["away_draws_5"]
        ) / 2.0
        features["draw_rate_gap_5"] = abs(
            features["home_draws_5"] - features["away_draws_5"]
        )
        features["expected_total_goals_5"] = (
            features["home_goals_for_5"]
            + features["away_goals_for_5"]
            + features["home_goals_against_5"]
            + features["away_goals_against_5"]
        ) / 2.0
        features.update(self._odds_features(match.uid))
        return features

    def _odds_features(self, uid: str) -> dict[str, float]:
        """Normalize pre-kickoff 1X2 snapshots supplied by the feature store.

        The expected shape is {"opening": {"home", "draw", "away"},
        "closing": {...}}. Missing phases fall back to the available phase.
        """
        payload = self._odds_by_uid.get(uid) or {}
        opening = payload.get("opening") or payload.get("closing") or {}
        closing = payload.get("closing") or payload.get("opening") or {}
        required = ("home", "draw", "away")
        if not all(float(opening.get(key, 0)) > 0 for key in required):
            return {"odds_available": 0.0}
        if not all(float(closing.get(key, 0)) > 0 for key in required):
            return {"odds_available": 0.0}
        inverse = np.asarray([1.0 / float(closing[key]) for key in required])
        implied = inverse / inverse.sum()
        closing_values = [float(closing[key]) for key in required]
        return {
            "opening_home": float(opening["home"]),
            "opening_draw": float(opening["draw"]),
            "opening_away": float(opening["away"]),
            "closing_home": closing_values[0],
            "closing_draw": closing_values[1],
            "closing_away": closing_values[2],
            "implied_home_probability": float(implied[0]),
            "implied_draw_probability": float(implied[1]),
            "implied_away_probability": float(implied[2]),
            "bookmaker_spread": max(closing_values) - min(closing_values),
            "odds_available": 1.0,
        }

    def _form_features(self, team: str) -> dict[str, float]:
        history = self._history[team]
        result: dict[str, float] = {}
        for window in (3, 5, 10):
            matches = history[-window:]
            denominator = float(len(matches) or 1)
            result[f"wins_{window}"] = sum(row.points == 3 for row in matches) / denominator
            result[f"draws_{window}"] = sum(row.points == 1 for row in matches) / denominator
            result[f"losses_{window}"] = sum(row.points == 0 for row in matches) / denominator
            result[f"points_{window}"] = sum(row.points for row in matches) / (
                3.0 * denominator
            )
        for window in (5, 10):
            matches = history[-window:]
            denominator = float(len(matches) or 1)
            goals_for = sum(row.goals_for for row in matches) / denominator
            goals_against = sum(row.goals_against for row in matches) / denominator
            result[f"goals_for_{window}"] = goals_for
            result[f"goals_against_{window}"] = goals_against
            result[f"goal_difference_{window}"] = goals_for - goals_against
        return result

    def _venue_features(self, match: HistoricalMatch) -> dict[str, float]:
        home_history = [row for row in self._history[match.home] if row.venue == "home"][-10:]
        away_history = [row for row in self._history[match.away] if row.venue == "away"][-10:]

        def strength(rows: list[_TeamResult]) -> float:
            return sum(row.points for row in rows) / (3.0 * float(len(rows) or 1))

        def win_rate(rows: list[_TeamResult]) -> float:
            return sum(row.points == 3 for row in rows) / float(len(rows) or 1)

        def goal_rate(rows: list[_TeamResult]) -> float:
            return sum(row.goals_for for row in rows) / float(len(rows) or 1)

        return {
            "home_strength": strength(home_history),
            "away_strength": strength(away_history),
            "home_win_rate": win_rate(home_history),
            "away_win_rate": win_rate(away_history),
            "home_goal_rate": goal_rate(home_history),
            "away_goal_rate": goal_rate(away_history),
        }

    def _h2h_features(self, match: HistoricalMatch) -> dict[str, float]:
        key = tuple(sorted((match.home, match.away)))
        prior = self._h2h[key][-10:]
        denominator = float(len(prior) or 1)
        home_wins = away_wins = draws = goal_difference = 0
        for old in prior:
            if old.home == match.home:
                home_goals, away_goals = old.home_score, old.away_score
            else:
                home_goals, away_goals = old.away_score, old.home_score
            goal_difference += home_goals - away_goals
            if home_goals > away_goals:
                home_wins += 1
            elif home_goals < away_goals:
                away_wins += 1
            else:
                draws += 1
        return {
            "last_h2h_matches": len(prior) / 10.0,
            "h2h_home_wins": home_wins / denominator,
            "h2h_away_wins": away_wins / denominator,
            "h2h_draws": draws / denominator,
            "h2h_goal_difference": goal_difference / denominator,
        }

    def _standings(self, competition: str, season: str) -> dict[str, dict[str, float]]:
        rows: dict[str, dict[str, float]] = defaultdict(
            lambda: {"played": 0.0, "points": 0.0, "gf": 0.0, "ga": 0.0}
        )
        for match in self._competition_matches[(competition, season)]:
            home = rows[match.home]
            away = rows[match.away]
            home["played"] += 1
            away["played"] += 1
            home["gf"] += match.home_score
            home["ga"] += match.away_score
            away["gf"] += match.away_score
            away["ga"] += match.home_score
            if match.home_score > match.away_score:
                home["points"] += 3
            elif match.home_score < match.away_score:
                away["points"] += 3
            else:
                home["points"] += 1
                away["points"] += 1
        ranked = sorted(
            rows,
            key=lambda team: (
                rows[team]["points"],
                rows[team]["gf"] - rows[team]["ga"],
                rows[team]["gf"],
            ),
            reverse=True,
        )
        size = float(max(len(ranked), 1))
        out: dict[str, dict[str, float]] = {}
        for index, team in enumerate(ranked, start=1):
            values = rows[team]
            out[team] = {
                "position": index / size,
                "raw_position": float(index),
                "points": values["points"] / max(values["played"] * 3.0, 1.0),
                "goal_difference": (values["gf"] - values["ga"])
                / max(values["played"], 1.0),
            }
        return out

    def _competition_features(
        self, match: HistoricalMatch, standings: dict[str, dict[str, float]]
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        size = float(max(len(standings), 1))
        for side, team in (("home", match.home), ("away", match.away)):
            current = standings.get(
                team,
                {
                    "position": 1.0,
                    "raw_position": size,
                    "points": 0.0,
                    "goal_difference": 0.0,
                },
            )
            key = (match.competition, match.season, team)
            previous = self._last_positions.get(key, int(current["raw_position"]))
            result[f"{side}_league_position"] = current["position"]
            result[f"{side}_league_points"] = current["points"]
            result[f"{side}_league_goal_difference"] = current["goal_difference"]
            result[f"{side}_recent_rank_change"] = (
                previous - current["raw_position"]
            ) / size
            self._last_positions[key] = int(current["raw_position"])
        return result

    @staticmethod
    def _rest(history: list[_TeamResult], as_of: datetime) -> float:
        if not history:
            return 14.0 / 30.0
        return min(max((as_of - history[-1].kickoff_at).days, 0), 30) / 30.0

    def _record(self, match: HistoricalMatch) -> None:
        home_points = (
            3 if match.home_score > match.away_score
            else 1 if match.home_score == match.away_score
            else 0
        )
        away_points = (
            3 if match.away_score > match.home_score
            else 1 if match.home_score == match.away_score
            else 0
        )
        self._history[match.home].append(
            _TeamResult(
                match.kickoff_at,
                match.home_score,
                match.away_score,
                home_points,
                "home",
            )
        )
        self._history[match.away].append(
            _TeamResult(
                match.kickoff_at,
                match.away_score,
                match.home_score,
                away_points,
                "away",
            )
        )
        self._h2h[tuple(sorted((match.home, match.away)))].append(match)
        self._competition_matches[(match.competition, match.season)].append(match)
