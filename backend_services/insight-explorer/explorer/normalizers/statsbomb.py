"""StatsBomb Open Data match → explorer.envelope.v1 (entity_type=fixture)."""

from __future__ import annotations

from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.clubs import resolve_club
from explorer.normalizers._envelope import build_envelope
from explorer.normalizers.espn import NormalizationError

# StatsBomb's match_status. "available" means the event data is published;
# anything else means the archive has the fixture but not its detail.
_PLAYED = {"available", "processed"}


def normalize(artifact: RawArtifact) -> dict[str, Any]:
    match = artifact.raw
    home = (match.get("home_team") or {}).get("home_team_name")
    away = (match.get("away_team") or {}).get("away_team_name")
    if not home or not away:
        raise NormalizationError("statsbomb match missing team")
    date = match.get("match_date")
    if not date:
        raise NormalizationError("statsbomb match missing match_date")

    scheduled_at = f"{date}T{match.get('kick_off') or '00:00:00.000'}"
    # kick_off is 'HH:MM:SS.mmm' local. Normalised to a UTC-marked timestamp
    # so the envelope's format holds; the millisecond field is dropped
    # because nothing downstream reads below the second.
    scheduled_at = scheduled_at.split(".")[0]
    if not scheduled_at.endswith("Z"):
        scheduled_at += "Z"

    home_score, away_score = match.get("home_score"), match.get("away_score")
    score = None
    if isinstance(home_score, int) and isinstance(away_score, int):
        score = {"home": home_score, "away": away_score}

    payload = {
        "external_fixture_id": artifact.external_id,
        "scheduled_at": scheduled_at,
        "status": "finished" if score is not None else "scheduled",
        "status_detail": (match.get("competition_stage") or {}).get("name"),
        "home_team": {
            "name": home,
            "external_id": str((match.get("home_team") or {}).get("home_team_id") or "") or None,
            "club_id": resolve_club(home),
            "short_name": None,
        },
        "away_team": {
            "name": away,
            "external_id": str((match.get("away_team") or {}).get("away_team_id") or "") or None,
            "club_id": resolve_club(away),
            "short_name": None,
        },
        "competition_key": artifact.competition_key,
        "season": artifact.season,
    }
    if score is not None:
        payload["score"] = score

    # The highest confidence in the registry for a finished match: this is a
    # curated archive with stable per-team external ids, so it both states the
    # result and can be joined to other sources without guessing at names.
    played = str(match.get("match_status", "")).lower() in _PLAYED
    return build_envelope(
        artifact,
        confidence=0.95 if (score is not None and played) else 0.75,
        payload=payload,
        entity_type="fixture",
    )
