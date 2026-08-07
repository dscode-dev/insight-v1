"""Build the historical similarity corpus from the Explorer's validated lake.

    validated/**/*.jsonl  ->  matches.jsonl + projection.jsonl

`atlas/intelligence/historical.py::load_dataset` reads the pair; without
`projection.jsonl` beside `matches.jsonl` every record's `.features`
degrades to `{}`.

LIVES IN THE PACKAGE, NOT IN scripts/. Two callers need it — the CLI
(`scripts/atlas_similarity_dataset_build.py`) and the scheduled refresh
(`atlas.vector_memory.refresh`). A watcher importing from `scripts/` would
point the dependency backwards: the script already imports `atlas.*`, so
`atlas` importing `scripts` closes a package-level cycle.

Reuses `HistoricalProjectionV3` -- System C's leakage-safe walk-forward
feature math (real Elo, attack/defense strength, market microstructure, h2h,
standings, rest days) -- as the OFFLINE feature source. Separate from
`atlas/strength/`, the LIVE engine that computes the same kinds of signal
incrementally for a match happening now. The two share the derived-signal
formulas (`atlas/strength/formulas.py`) where their raw ingredients line up,
and each converts the handful of fields the other exposes differently (v3's
positions/rest/odds arrive pre-normalized; the live path keeps raw integers,
day counts and prices).

`lake_dir` must be Explorer's `validated/` layer specifically, never the lake
root -- same caveat as `scripts/atlas_strength_backfill.py`.
"""

from __future__ import annotations

import glob
import json
import uuid
from dataclasses import replace
from datetime import date, datetime

from atlas.outcome.labels import result_label
from atlas.outcome.projection import HistoricalMatch
from atlas.outcome.projection_v3 import HistoricalProjectionV3
from atlas.strength.formulas import h2h_advantage, unit_strength_ratio

_NS = uuid.UUID("00000000-0000-0000-0000-0000a71a5dee")  # matches atlas/outcome/train.py's _NS


# A source's own id names a source's ROW, not the match. Football-Data calls
# the 2020-11-07 Barcelona–Betis `fd-2021-SP1-0075`, openfootball calls it
# `of-es.1-2020-21-0075`, StatsBomb `sb-3773477` — one match, three ids, and
# keying the uid on them put the same 90 minutes into the corpus three times.
# That is not merely redundant: `project()` replays matches in kickoff order
# and updates Elo, attack/defense and h2h as it goes, so a triplicated match
# moved every rating three times for one real game, and similarity returned it
# as three independent neighbours — inflating agreement by construction.
#
# WHY THE DATE AND NOT THE FULL KICKOFF. The sources agree on the day and
# disagree on the clock: Football-Data publishes no time and the normalizer
# writes 2023-08-13T00:00:00Z, openfootball carries the real
# 2023-08-13T19:30:00Z. Truncating to the UTC date makes those one match
# without needing a tolerance window.
#
# WHY NOT DROP THE DATE ENTIRELY. A league season plays each ordered pair
# once, which would make (competition, season, home, away) sufficient — but
# not every competition is a league. A Champions League side can host the
# same opponent in the group stage and again in a semi-final within one
# season: same ordered pair, two different matches. The date separates them.
def _match_uid(competition: str, season: str, home: str, away: str, day: str) -> str:
    return str(uuid.uuid5(_NS, f"{competition}|{season}|{home}|{away}|{day}"))


# Applied only where sources disagree on the same field. StatsBomb is
# hand-curated event data, Football-Data is a maintained results archive, and
# openfootball is community-edited — so this is descending order of how much
# review a number has had before publication.
_SOURCE_RANK = {"statsbomb": 0, "football_data": 1, "openfootball": 2}


def _source_of(envelope: dict, path: str) -> str:
    """The producing source. `selected_source` is null across the current lake,
    so fall back to the layout that wrote the file:
    validated/{competition}/{season}/{SOURCE}/{entity_type}/part-*.jsonl."""
    named = envelope.get("selected_source")
    if named:
        return str(named)
    parts = path.replace("\\", "/").split("/")
    return parts[-3] if len(parts) >= 3 else "unknown"


def _kickoff_precision(moment: datetime) -> int:
    """1 when the record carries a real kickoff time, 0 when it is a placeholder.

    Football-Data publishes dates without times and the normalizer writes
    midnight; openfootball carries the actual 19:30. Both are "the same match",
    so the merge keeps the informative one — and this is decided separately
    from `_SOURCE_RANK`, which is about whose FACTS to trust. A source can be
    the better authority on a final score while recording no clock at all.
    """
    return 0 if (moment.hour, moment.minute, moment.second) == (0, 0, 0) else 1


def _load(lake_dir: str) -> tuple[list[HistoricalMatch], dict[str, tuple[str, ...]], dict]:
    best: dict[str, tuple[int, HistoricalMatch]] = {}
    best_kickoff: dict[str, datetime] = {}
    sources_by_uid: dict[str, set[str]] = {}
    pairs: dict[tuple[str, str, str, str], set[date]] = {}
    stats = {"read": 0, "score_conflicts": 0}

    for path in glob.glob(f"{lake_dir}/**/*.jsonl", recursive=True):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                envelope = json.loads(line)
                payload = envelope.get("payload") or {}
                if payload.get("status") != "finished":
                    continue
                score = payload.get("score") or {}
                if score.get("home") is None or score.get("away") is None:
                    continue
                home = (payload.get("home_team") or {}).get("club_id") or (payload.get("home_team") or {}).get("name")
                away = (payload.get("away_team") or {}).get("club_id") or (payload.get("away_team") or {}).get("name")
                scheduled_at = payload.get("scheduled_at")
                if not (home and away and scheduled_at):
                    continue
                competition = (envelope.get("competition") or {}).get("competition_key") or ""
                season = str(envelope.get("season") or "")
                kickoff = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
                uid = _match_uid(
                    competition, season, str(home), str(away),
                    kickoff.date().isoformat(),
                )
                source = _source_of(envelope, path)
                stats["read"] += 1
                pairs.setdefault(
                    (competition, season, str(home), str(away)), set()
                ).add(kickoff.date())

                candidate = HistoricalMatch(
                    uid=uid,
                    kickoff_at=kickoff,
                    competition=competition,
                    season=season,
                    home=str(home),
                    away=str(away),
                    home_score=int(score["home"]),
                    away_score=int(score["away"]),
                    neutral=(competition == "world_cup"),
                )
                sources_by_uid.setdefault(uid, set()).add(source)

                incumbent_kickoff = best_kickoff.get(uid)
                if incumbent_kickoff is None or (
                    _kickoff_precision(candidate.kickoff_at),
                    -candidate.kickoff_at.timestamp(),
                ) > (
                    _kickoff_precision(incumbent_kickoff),
                    -incumbent_kickoff.timestamp(),
                ):
                    best_kickoff[uid] = candidate.kickoff_at

                rank = _SOURCE_RANK.get(source, len(_SOURCE_RANK))
                held = best.get(uid)
                if held is None:
                    best[uid] = (rank, candidate)
                    continue
                held_rank, held_match = held
                if (candidate.home_score, candidate.away_score) != (
                    held_match.home_score, held_match.away_score
                ):
                    # Reported rather than resolved silently: sources
                    # disagreeing about a final score means one of them is
                    # wrong about a fact, and that is worth seeing in the
                    # summary even though the ranking picks a winner.
                    stats["score_conflicts"] += 1
                if rank < held_rank:
                    best[uid] = (rank, candidate)

    stats["unique"] = len(best)
    stats["collapsed"] = stats["read"] - len(best)
    stats["multi_source"] = sum(1 for names in sources_by_uid.values() if len(names) > 1)

    # The one way the date can fail to identify a match: a source recording a
    # late kickoff in local time and another in UTC put the same match on
    # adjacent days, so it stays split. Two real matches between the same
    # ordered pair on consecutive days do not happen. Counted rather than
    # merged — merging on a guess is what this whole change is undoing — so
    # a non-zero value is a signal to go look at the source's timezone
    # handling. Zero across the current European corpus, where kickoffs sit
    # far from midnight UTC.
    stats["adjacent_day_pairs"] = sum(
        1
        for days in pairs.values()
        for a, b in ((min(days), max(days)),)
        if len(days) > 1 and (b - a).days == 1
    )
    merged = [
        replace(match, kickoff_at=best_kickoff[uid]) for uid, (_, match) in best.items()
    ]
    return (
        merged,
        {uid: tuple(sorted(names)) for uid, names in sources_by_uid.items()},
        stats,
    )


def _derived_v2_signals(features: dict[str, float]) -> dict[str, float]:
    """Maps HistoricalProjectionV3's raw feature names onto the derived
    scalars the live similarity engine (v2) reads — see
    `atlas/intelligence/similarity_engine/engine.py`'s `_WEIGHTS`.
    Reuses `atlas/strength/formulas.py` where the raw shapes line up
    directly; small inline conversions where v3 pre-normalizes a field
    the live path keeps raw (documented at each spot below)."""
    out: dict[str, float] = {}
    out["elo_difference"] = max(-1.0, min(1.0, features.get("elo_difference", 0.0)))
    out["home_attack_strength"] = unit_strength_ratio(features.get("home_attack_strength", 1.0))
    out["away_attack_strength"] = unit_strength_ratio(features.get("away_attack_strength", 1.0))
    out["home_defense_strength"] = unit_strength_ratio(features.get("home_defense_strength", 1.0))
    out["away_defense_strength"] = unit_strength_ratio(features.get("away_defense_strength", 1.0))

    # v3's h2h_home_wins/away_wins/draws are already ratios (count /
    # max(len(prior), 1)) that sum to 1 when there IS prior history and
    # to 0 when there isn't — h2h_advantage's zero-total guard already
    # gives the right "no data yet" None in that empty case, so feeding
    # the ratios straight in (instead of raw counts) is mathematically
    # equivalent here.
    advantage = h2h_advantage(
        features.get("h2h_home_wins", 0.0),
        features.get("h2h_away_wins", 0.0),
        features.get("h2h_draws", 0.0),
    )
    if advantage is not None:
        out["h2h_advantage"] = advantage

    # v3 exposes normalized table position (index/league_size, lower is
    # better) rather than the raw integer rank atlas/strength/repository.py
    # uses live — the gap is already naturally bounded [-1, 1] on this scale.
    home_position = features.get("home_league_position")
    away_position = features.get("away_league_position")
    if home_position and away_position:
        out["table_position_gap"] = max(-1.0, min(1.0, away_position - home_position))

    # v3 exposes rest days pre-normalized to /30 rather than raw day
    # counts — undo that scaling before applying the live path's /14 cap
    # so both paths agree on what a "full" rest advantage looks like.
    home_rest = features.get("home_rest_days")
    away_rest = features.get("away_rest_days")
    if home_rest is not None and away_rest is not None:
        out["rest_advantage"] = max(-1.0, min(1.0, ((home_rest - away_rest) * 30.0) / 14.0))

    # v3 exposes raw opening/closing PRICES plus an already-normalized
    # CLOSING implied probability; derive the matching opening implied
    # probability the same way (1/price, renormalized across outcomes).
    if features.get("odds_available"):
        opening_prices = (
            features.get("opening_home"), features.get("opening_draw"), features.get("opening_away"),
        )
        if all(price and price > 0 for price in opening_prices):
            inverse = [1.0 / price for price in opening_prices]
            opening_home_prob = inverse[0] / sum(inverse)
            closing_home_prob = features.get("implied_home_probability")
            if closing_home_prob is not None:
                out["line_movement"] = max(
                    -1.0, min(1.0, closing_home_prob - opening_home_prob)
                )
    return out


def build(lake_dir: str, out_dir: str) -> dict:
    import os

    matches, sources_by_uid, load_stats = _load(lake_dir)
    projector = HistoricalProjectionV3()
    rows = projector.project(matches)

    os.makedirs(out_dir, exist_ok=True)
    matches_by_uid = {m.uid: m for m in matches}
    with open(f"{out_dir}/matches.jsonl", "w", encoding="utf-8") as matches_fh, \
         open(f"{out_dir}/projection.jsonl", "w", encoding="utf-8") as projection_fh:
        for row in rows:
            match = matches_by_uid[row.uid]
            matches_fh.write(json.dumps({
                "uid": row.uid,
                "competition": row.competition,
                "season": row.season,
                "kickoff_at": row.kickoff_at.isoformat(),
                "home": match.home,
                "away": match.away,
                "home_score": match.home_score,
                "away_score": match.away_score,
                "label": result_label(match.home_score, match.away_score),
                "sources": list(sources_by_uid.get(row.uid, ("unknown",))),
            }) + "\n")
            features = dict(row.features)
            features.update(_derived_v2_signals(row.features))
            projection_fh.write(json.dumps({"uid": row.uid, "features": features}) + "\n")

    summary = {"rows": len(rows), "out_dir": out_dir, **load_stats}
    print(json.dumps(summary))
    return summary
