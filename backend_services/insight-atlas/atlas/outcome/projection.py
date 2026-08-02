"""Leakage-safe historical projection.

Turns an ordered list of finished matches into outcome_v1 feature vectors +
result labels. The ONLY anti-leakage invariant: every feature for match M is
computed using strictly `kickoff_at < M.kickoff_at` data — the match never
contributes to its own features, and no future match is ever consulted.

Pure + deterministic: same input order → same output (reproducible datasets).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from atlas.outcome.labels import result_label
from atlas.outcome.schema import FEATURE_NAMES_OUTCOME, outcome_defaults


@dataclass(frozen=True)
class HistoricalMatch:
    uid: str
    kickoff_at: datetime
    competition: str
    season: str
    home: str          # canonical team id
    away: str
    home_score: int
    away_score: int
    neutral: bool = False


@dataclass(frozen=True)
class ProjectedRow:
    uid: str
    kickoff_at: datetime
    features: dict[str, float]
    label: str
    prior_matches: int  # # of prior matches that fed this row (0 = cold start)

    def vector(self) -> list[float]:
        d = outcome_defaults()
        d.update({k: float(v) for k, v in self.features.items() if k in d})
        return [float(d[name]) for name in FEATURE_NAMES_OUTCOME]


class HistoricalProjection:
    """Streams matches in chronological order, projecting each BEFORE updating
    history — guaranteeing no future leakage by construction."""

    def __init__(self) -> None:
        self._hist: dict[str, list[tuple[datetime, int, int, int]]] = {}
        self._h2h: dict[tuple[str, str], list[tuple[datetime, str, int, int]]] = {}

    def project(self, matches: Iterable[HistoricalMatch]) -> list[ProjectedRow]:
        ordered = sorted(matches, key=lambda m: m.kickoff_at)
        rows: list[ProjectedRow] = []
        for m in ordered:
            as_of = m.kickoff_at
            hf = self._team_features(m.home, as_of)
            af = self._team_features(m.away, as_of)
            feats = {
                "home_form_pts5": hf["form"],
                "away_form_pts5": af["form"],
                "home_gf5": hf["gf"], "home_ga5": hf["ga"],
                "away_gf5": af["gf"], "away_ga5": af["ga"],
                "home_gd5": hf["gf"] - hf["ga"],
                "away_gd5": af["gf"] - af["ga"],
                "h2h_home_winrate": self._h2h_winrate(m.home, m.away, as_of),
                "home_rest_days": min(hf["rest"], 30.0) / 30.0,
                "away_rest_days": min(af["rest"], 30.0) / 30.0,
                "home_advantage": 0.0 if m.neutral else 1.0,
            }
            rows.append(ProjectedRow(
                uid=m.uid, kickoff_at=as_of, features=feats,
                label=result_label(m.home_score, m.away_score),
                prior_matches=hf["n"] + af["n"],
            ))
            # update history AFTER projecting this match
            self._record(m)
        return rows

    # -- internals (strict `< as_of` everywhere) --

    def _team_features(self, team: str, as_of: datetime) -> dict[str, float]:
        h = [x for x in self._hist.get(team, []) if x[0] < as_of]
        last5 = h[-5:]
        if not last5:
            d = outcome_defaults()
            return {"form": 1.0, "gf": d["home_gf5"], "ga": d["home_ga5"],
                    "rest": 14.0, "n": 0}
        n = len(last5)
        pts = sum(x[3] for x in last5)
        gf = sum(x[1] for x in last5) / n
        ga = sum(x[2] for x in last5) / n
        rest = (as_of - h[-1][0]).days
        return {"form": pts / n, "gf": gf, "ga": ga, "rest": float(rest), "n": n}

    def _h2h_winrate(self, home: str, away: str, as_of: datetime) -> float:
        key = tuple(sorted([home, away]))
        prior = [x for x in self._h2h.get(key, []) if x[0] < as_of]
        if not prior:
            return 0.5
        hw = sum(
            1 for x in prior
            if (x[1] == home and x[2] > x[3]) or (x[1] == away and x[3] > x[2])
        )
        return hw / len(prior)

    def _record(self, m: HistoricalMatch) -> None:
        hp = 3 if m.home_score > m.away_score else 1 if m.home_score == m.away_score else 0
        ap = 3 if m.away_score > m.home_score else 1 if m.home_score == m.away_score else 0
        self._hist.setdefault(m.home, []).append((m.kickoff_at, m.home_score, m.away_score, hp))
        self._hist.setdefault(m.away, []).append((m.kickoff_at, m.away_score, m.home_score, ap))
        self._h2h.setdefault(tuple(sorted([m.home, m.away])), []).append(
            (m.kickoff_at, m.home, m.home_score, m.away_score)
        )
