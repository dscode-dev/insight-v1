"""FBRef schedule row → explorer.envelope.v1 (entity_type=fixture)."""

from __future__ import annotations

import re
from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.clubs import resolve_club
from explorer.config import COMPETITIONS
from explorer.datalake.lake import checksum
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

    comp_def = COMPETITIONS.get(artifact.competition_key)
    return {
        "schema_version": "explorer.envelope.v1",
        "source": artifact.source,
        "provider": artifact.provider,
        "source_type": artifact.source_type,
        "trust_level": artifact.trust_level,
        "confidence": 0.93 if status == "finished" else 0.7,
        "captured_at": artifact.retrieved_at,
        "entity_type": "fixture",
        "external_id": artifact.external_id,
        "canonical_match_id": None,
        "competition": {"competition_key": artifact.competition_key, "competition_id": None,
                        "external_id": None, "name": comp_def.name if comp_def else None},
        "season": artifact.season,
        "payload": payload,
        "provenance": {"url": artifact.url, "retrieved_at": artifact.retrieved_at,
                       "method": artifact.method, "parser": artifact.provider,
                       "checksum": checksum(artifact.raw), "license_note": artifact.license_note},
    }
