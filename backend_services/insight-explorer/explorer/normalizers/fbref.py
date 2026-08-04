"""FBRef schedule row → explorer.envelope.v1 (entity_type=fixture)."""

from __future__ import annotations

import re
from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.clubs import resolve_club
from explorer.normalizers._envelope import build_envelope
from explorer.normalizers.espn import NormalizationError

_SCORE = re.compile(r"(\d+)\s*[–-]\s*(\d+)")


def normalize(artifact: RawArtifact) -> dict[str, Any]:
    row = artifact.raw
    home, away = row.get("home_team"), row.get("away_team")
    if not home or not away:
        raise NormalizationError("fbref row missing team")
    date = row.get("date")
    if not date:
        raise NormalizationError("fbref row missing date")
    scheduled_at = f"{date}T00:00:00Z"
    m = _SCORE.search(row.get("score", ""))
    score = {"home": int(m.group(1)), "away": int(m.group(2))} if m else None
    status = "finished" if score else "scheduled"

    payload = {
        "external_fixture_id": artifact.external_id,
        "scheduled_at": scheduled_at,
        "status": status,
        "status_detail": row.get("score"),
        "venue": row.get("venue") or None,
        "home_team": {"name": home, "external_id": None, "club_id": resolve_club(home),
                      "short_name": None},
        "away_team": {"name": away, "external_id": None, "club_id": resolve_club(away),
                      "short_name": None},
        "competition_key": artifact.competition_key,
        "season": artifact.season,
    }
    if score is not None:
        payload["score"] = score

    return build_envelope(
        artifact, confidence=0.93 if status == "finished" else 0.7, payload=payload,
    )
