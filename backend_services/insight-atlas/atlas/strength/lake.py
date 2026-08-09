"""Reads finished-match results out of Explorer's validated fixture lake.

Match RESULTS are not part of Atlas's live canonical-event stream (that
stream only ever carries in-play signals — odds, stats, cards; there is
no structured final-score event). Explorer's history is the system of
record for "this match finished N-M" — the same source
`atlas/outcome/train.py::_load` and
`atlas/intelligence/historical.py::load_dataset` already trust. This
module parses the identical envelope shape (`payload.status=="finished"`,
`payload.score.home/away`) but yields `strength.models.MatchResult`
instead of the offline `HistoricalMatch` dataclass, keeping the live
strength engine independent of `atlas/outcome/` (explicitly outside V1
scope per ATLAS_V1_FROZEN.md).

Chronological ordering matters: Elo/rolling-window state is only
meaningful when results are folded in kickoff-order. `iter_match_results`
always yields oldest-first regardless of file/line order on disk. If a
large historical backfill is ever inserted into the lake with kickoff
dates OLDER than matches already folded into the state, the correct
remedy is a full rebuild via `scripts/atlas_strength_backfill.py` — this
reader does not attempt to detect or repair a corrupted replay order.
"""

from __future__ import annotations

import glob
import json
import uuid
from datetime import datetime

from atlas.intelligence.historical import normalize_competition
from atlas.strength.models import MatchResult

_NS = uuid.UUID("00000000-0000-0000-0000-0000a71a5dee")  # matches atlas/outcome/train.py's _NS


def iter_match_results(lake_dir: str) -> list[MatchResult]:
    """All finished matches under `lake_dir`, oldest kickoff first."""
    results: list[MatchResult] = []
    for path in glob.glob(f"{lake_dir}/**/*.jsonl", recursive=True):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                parsed = _parse_line(line)
                if parsed is not None:
                    results.append(parsed)
    results.sort(key=lambda r: (r.kickoff_at, r.uid))
    return results


def _parse_line(line: str) -> MatchResult | None:
    envelope = json.loads(line)
    payload = envelope.get("payload") or {}
    if payload.get("status") != "finished":
        return None
    score = payload.get("score") or {}
    if score.get("home") is None or score.get("away") is None:
        return None
    home = (payload.get("home_team") or {}).get("club_id") or (payload.get("home_team") or {}).get("name")
    away = (payload.get("away_team") or {}).get("club_id") or (payload.get("away_team") or {}).get("name")
    scheduled_at = payload.get("scheduled_at")
    if not (home and away and scheduled_at):
        return None
    raw_competition = (envelope.get("competition") or {}).get("competition_key") or ""
    competition = normalize_competition(raw_competition) if raw_competition else ""
    external_id = envelope.get("external_id")
    return MatchResult(
        uid=str(uuid.uuid5(_NS, str(external_id))),
        competition=competition,
        season=str(envelope.get("season") or ""),
        kickoff_at=_parse_time(scheduled_at),
        home=str(home),
        away=str(away),
        home_score=int(score["home"]),
        away_score=int(score["away"]),
    )


def _parse_time(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
