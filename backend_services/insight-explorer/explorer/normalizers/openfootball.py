"""openfootball/football.json match → explorer.envelope.v1 (entity_type=fixture)."""

from __future__ import annotations

from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.clubs import resolve_club
from explorer.normalizers._envelope import build_envelope
from explorer.normalizers.espn import NormalizationError


def _score(match: dict[str, Any]) -> dict[str, int] | None:
    """football.json carries `score.ft` as [home, away], plus optional `ht`.

    A fixture that has not been played has no `score` key at all, which is
    how a scheduled match is told apart from a 0-0 — the distinction the
    `status` below depends on.
    """
    raw = match.get("score")
    if not isinstance(raw, dict):
        return None
    ft = raw.get("ft")
    if not isinstance(ft, list) or len(ft) != 2:
        return None
    try:
        out = {"home": int(ft[0]), "away": int(ft[1])}
    except (TypeError, ValueError):
        return None
    ht = raw.get("ht")
    if isinstance(ht, list) and len(ht) == 2:
        try:
            out["halftime_home"] = int(ht[0])
            out["halftime_away"] = int(ht[1])
        except (TypeError, ValueError):
            pass
    return out


def normalize(artifact: RawArtifact) -> dict[str, Any]:
    match = artifact.raw
    home, away = match.get("team1"), match.get("team2")
    if not home or not away:
        raise NormalizationError("openfootball match missing team")
    date = match.get("date")
    if not date:
        raise NormalizationError("openfootball match missing date")

    # The file gives a local date and sometimes a local time, with no zone.
    # Midnight UTC is used when there is no time rather than inventing one:
    # a fabricated kick-off would look like real precision downstream.
    scheduled_at = f"{date}T{match.get('time') or '00:00'}:00Z"
    score = _score(match)

    payload = {
        "external_fixture_id": artifact.external_id,
        "scheduled_at": scheduled_at,
        "status": "finished" if score is not None else "scheduled",
        "status_detail": match.get("round"),
        "home_team": {"name": home, "external_id": None,
                      "club_id": resolve_club(home), "short_name": None},
        "away_team": {"name": away, "external_id": None,
                      "club_id": resolve_club(away), "short_name": None},
        "competition_key": artifact.competition_key,
        "season": artifact.season,
    }
    if score is not None:
        payload["score"] = score

    # Below Football-Data's 0.92 for a finished match. The data is reliable,
    # but team names are free text with no external id, so joining it to
    # another source depends entirely on name resolution.
    return build_envelope(
        artifact,
        confidence=0.88 if score is not None else 0.7,
        payload=payload,
        entity_type="fixture",
    )
