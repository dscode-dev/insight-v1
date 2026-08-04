"""Football-Data CSV row → explorer.envelope.v1 (entity_type=fixture)."""

from __future__ import annotations

from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.adapters.football_data import parse_fd_date
from explorer.clubs import resolve_club
from explorer.normalizers._envelope import build_envelope
from explorer.normalizers.espn import NormalizationError


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize(artifact: RawArtifact) -> dict[str, Any]:
    row = artifact.raw
    home, away = row.get("HomeTeam"), row.get("AwayTeam")
    if not home or not away:
        raise NormalizationError("football-data row missing team")
    scheduled_at = parse_fd_date(row.get("Date", "")) or None
    if not scheduled_at:
        raise NormalizationError("football-data row missing/invalid date")
    fthg, ftag = _int(row.get("FTHG")), _int(row.get("FTAG"))
    score = None
    if fthg is not None and ftag is not None:
        score = {"home": fthg, "away": ftag}
        hthg, htag = _int(row.get("HTHG")), _int(row.get("HTAG"))
        if hthg is not None:
            score["halftime_home"] = hthg
        if htag is not None:
            score["halftime_away"] = htag
    status = "finished" if score is not None else "scheduled"

    payload = {
        "external_fixture_id": artifact.external_id,
        "scheduled_at": scheduled_at,
        "status": status,
        "status_detail": row.get("FTR"),
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
        artifact, confidence=0.92 if status == "finished" else 0.7, payload=payload,
    )
