"""ESPN raw event → explorer.envelope.v1 (entity_type=fixture).

Pure function of a RawArtifact. No network, no validation, no AI. Team
identity is resolved deterministically via the Club Registry (Step 7
backbone); names that don't resolve are left with club_id=null and surfaced
later as an `entity_unresolved` candidate — never fabricated.
"""

from __future__ import annotations

from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.clubs import resolve_club
from explorer.config import COMPETITIONS
from explorer.normalizers._envelope import build_envelope

# ESPN status type name → normalized envelope status.
_STATUS_MAP = {
    "STATUS_SCHEDULED": "scheduled",
    "STATUS_FULL_TIME": "finished",
    "STATUS_FINAL": "finished",
    "STATUS_FT": "finished",
    "STATUS_HALFTIME": "halftime",
    "STATUS_FIRST_HALF": "live",
    "STATUS_SECOND_HALF": "live",
    "STATUS_IN_PROGRESS": "live",
    "STATUS_POSTPONED": "postponed",
    "STATUS_ABANDONED": "abandoned",
    "STATUS_CANCELED": "abandoned",
}


class NormalizationError(ValueError):
    """Raw event is missing fields required to build a fixture payload."""


def _team(competitor: dict[str, Any]) -> dict[str, Any]:
    team = competitor.get("team", {})
    name = team.get("displayName") or team.get("name") or team.get("shortDisplayName")
    if not name:
        raise NormalizationError("competitor without a team name")
    return {
        "name": name,
        "external_id": str(team.get("id")) if team.get("id") is not None else None,
        "club_id": resolve_club(name),
        "short_name": team.get("abbreviation"),
    }


def _score(competitor: dict[str, Any]) -> int | None:
    val = competitor.get("score")
    if val in (None, ""):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def normalize(artifact: RawArtifact) -> dict[str, Any]:
    """Return a complete explorer.envelope.v1 dict (unvalidated)."""
    event = artifact.raw
    comps = event.get("competitions") or []
    if not comps:
        raise NormalizationError("event has no competitions[]")
    comp = comps[0]
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home is None or away is None:
        raise NormalizationError("event missing home/away competitor")

    status_type = ((comp.get("status") or {}).get("type") or {})
    status = _STATUS_MAP.get(status_type.get("name", ""), "unknown")
    scheduled_at = event.get("date")
    if not scheduled_at:
        raise NormalizationError("event missing date")
    # ESPN dates look like 2022-11-02T19:00Z → make RFC3339 with seconds.
    if scheduled_at.endswith("Z") and "T" in scheduled_at and scheduled_at.count(":") == 1:
        scheduled_at = scheduled_at[:-1] + ":00Z"

    home_score, away_score = _score(home), _score(away)
    score: dict[str, Any] | None = None
    if home_score is not None and away_score is not None:
        score = {"home": home_score, "away": away_score}

    payload = {
        "external_fixture_id": artifact.external_id,
        "scheduled_at": scheduled_at,
        "status": status,
        "status_detail": status_type.get("detail"),
        "venue": (comp.get("venue") or {}).get("fullName"),
        "home_team": _team(home),
        "away_team": _team(away),
        "competition_key": artifact.competition_key,
        "season": artifact.season,
    }
    if score is not None:
        payload["score"] = score

    comp_def = COMPETITIONS.get(artifact.competition_key)
    confidence = 0.9 if status == "finished" else 0.75

    return build_envelope(
        artifact, confidence=confidence, payload=payload,
        competition_external_id=comp_def.espn_league if comp_def else None,
    )
