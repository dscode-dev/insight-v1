"""API-Football fixture → explorer.envelope.v1 (entity_type=fixture)."""

from __future__ import annotations

from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.clubs import resolve_club
from explorer.normalizers._envelope import build_envelope
from explorer.normalizers.espn import NormalizationError

# API-Football's short status codes → our vocabulary.
_STATUS = {
    "FT": "finished", "AET": "finished", "PEN": "finished",
    "NS": "scheduled", "TBD": "scheduled",
    "1H": "live", "2H": "live", "HT": "live", "ET": "live", "BT": "live", "P": "live",
    "PST": "postponed", "CANC": "cancelled", "ABD": "cancelled",
    "SUSP": "suspended", "INT": "suspended", "AWD": "finished", "WO": "finished",
}


def normalize(artifact: RawArtifact) -> dict[str, Any]:
    item = artifact.raw
    fixture = item.get("fixture") or {}
    teams = item.get("teams") or {}
    home, away = teams.get("home") or {}, teams.get("away") or {}
    if not home.get("name") or not away.get("name"):
        raise NormalizationError("api-football fixture missing team")
    scheduled_at = fixture.get("date")
    if not scheduled_at:
        raise NormalizationError("api-football fixture missing date")

    short = str(((fixture.get("status") or {}).get("short")) or "")
    status = _STATUS.get(short, "scheduled")

    goals = item.get("goals") or {}
    score = None
    if isinstance(goals.get("home"), int) and isinstance(goals.get("away"), int):
        score = {"home": goals["home"], "away": goals["away"]}
        halftime = (item.get("score") or {}).get("halftime") or {}
        if isinstance(halftime.get("home"), int):
            score["halftime_home"] = halftime["home"]
        if isinstance(halftime.get("away"), int):
            score["halftime_away"] = halftime["away"]

    # A status the map does not know is NOT silently treated as scheduled
    # when a score exists: a finished match filed as scheduled would be
    # invisible to anything reading results.
    if score is not None and status == "scheduled" and short not in ("NS", "TBD"):
        status = "finished"

    payload = {
        "external_fixture_id": artifact.external_id,
        "scheduled_at": scheduled_at,
        "status": status,
        "status_detail": (fixture.get("status") or {}).get("long"),
        "home_team": {"name": home["name"], "external_id": str(home.get("id") or "") or None,
                      "club_id": resolve_club(home["name"]), "short_name": None},
        "away_team": {"name": away["name"], "external_id": str(away.get("id") or "") or None,
                      "club_id": resolve_club(away["name"]), "short_name": None},
        "competition_key": artifact.competition_key,
        "season": artifact.season,
    }
    if score is not None:
        payload["score"] = score

    return build_envelope(
        artifact,
        confidence=0.93 if status == "finished" else 0.75,
        payload=payload,
        entity_type="fixture",
    )
