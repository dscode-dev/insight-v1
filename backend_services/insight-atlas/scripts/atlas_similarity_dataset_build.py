"""Generates matches.jsonl + projection.jsonl for the offline historical
similarity corpus `atlas/intelligence/historical.py::load_dataset` reads.

Fixes a real production gap found during ATLAS-SIM-A: the configured
default dataset path (`ATLAS_INTELLIGENCE_DATASET_PATH`, e.g.
`/var/atlas/datasets/outcome_v4-mld6-20260623/matches.jsonl`) has no
generator anywhere in this repo — no `ml_d5`/`ml_d6` script exists
(confirmed via `git log --all`). Without `projection.jsonl` next to
`matches.jsonl`, `load_dataset()` degrades every record's `.features`
to `{}` (see the historical.py fix in the same change) — this script is
what actually produces that file.

Reuses `HistoricalProjectionV3` — System C's proven, leakage-safe
walk-forward feature math (real Elo, attack/defense strength, market
microstructure, h2h, standings, rest days) — as the OFFLINE feature
source for the historical corpus. This is separate from and does not
modify `atlas/strength/` (the LIVE engine, which computes the same kind
of signals incrementally for a match happening right now instead of via
batch replay over closed history) — the two paths share the derived-
signal formulas (`atlas/strength/formulas.py`) where their raw
ingredients line up, and each has its own small conversion for the
handful of fields the two feature pipelines expose differently
(v3's positions/rest/odds are pre-normalized; the live path keeps raw
integers/day-counts/prices).

Usage:
    python -m scripts.atlas_similarity_dataset_build <validated_lake_dir> <out_dir>

`<validated_lake_dir>` must point at Explorer's `validated/` layer
specifically, never the lake root — same caveat as
`scripts/atlas_strength_backfill.py`.
"""

from __future__ import annotations

import glob
import json
import sys
import uuid
from datetime import datetime

from atlas.outcome.labels import result_label
from atlas.outcome.projection import HistoricalMatch
from atlas.outcome.projection_v3 import HistoricalProjectionV3
from atlas.strength.formulas import h2h_advantage, unit_strength_ratio

_NS = uuid.UUID("00000000-0000-0000-0000-0000a71a5dee")  # matches atlas/outcome/train.py's _NS


def _load(lake_dir: str) -> tuple[list[HistoricalMatch], dict[str, tuple[str, ...]]]:
    matches: list[HistoricalMatch] = []
    sources_by_uid: dict[str, tuple[str, ...]] = {}
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
                uid = str(uuid.uuid5(_NS, str(envelope.get("external_id"))))
                matches.append(HistoricalMatch(
                    uid=uid,
                    kickoff_at=datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00")),
                    competition=competition,
                    season=str(envelope.get("season") or ""),
                    home=str(home),
                    away=str(away),
                    home_score=int(score["home"]),
                    away_score=int(score["away"]),
                    neutral=(competition == "world_cup"),
                ))
                raw_sources = envelope.get("sources") or [envelope.get("selected_source") or "unknown"]
                sources_by_uid[uid] = tuple(str(s) for s in raw_sources if s)
    return matches, sources_by_uid


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

    matches, sources_by_uid = _load(lake_dir)
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

    summary = {"rows": len(rows), "out_dir": out_dir}
    print(json.dumps(summary))
    return summary


def main() -> None:
    lake_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/validated"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/similarity-dataset"
    build(lake_dir, out_dir)


if __name__ == "__main__":
    main()
