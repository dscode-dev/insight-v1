"""Football-Data artifact → explorer.envelope.v1.

One CSV row produces up to three artifacts (fixture, stats, one odds_snapshot
per bookmaker), so this module dispatches on the artifact's entity_type
instead of assuming a fixture.
"""

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
    kind = artifact.entity_type or "fixture"
    if kind == "stats":
        return _normalize_stats(artifact)
    if kind == "odds_snapshot":
        return _normalize_odds(artifact)
    return _normalize_fixture(artifact)


def _normalize_fixture(artifact: RawArtifact) -> dict[str, Any]:
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


def _normalize_stats(artifact: RawArtifact) -> dict[str, Any]:
    raw = artifact.raw
    fixture_id = raw.get("_fixture_id")
    if not fixture_id:
        raise NormalizationError("stats artifact missing _fixture_id")
    payload = {
        "external_fixture_id": fixture_id,
        "home": raw.get("home") or {},
        "away": raw.get("away") or {},
    }
    # Lower than a fixture's 0.92: these are post-match counts from a
    # secondary feed, not the result itself, and they are the field most
    # often missing or revised in this source.
    return build_envelope(artifact, confidence=0.85, payload=payload,
                          entity_type="stats")


def _normalize_odds(artifact: RawArtifact) -> dict[str, Any]:
    raw = artifact.raw
    fixture_id = raw.get("_fixture_id")
    selections = raw.get("selections") or []
    if not fixture_id:
        raise NormalizationError("odds artifact missing _fixture_id")
    if not selections:
        raise NormalizationError("odds artifact carries no selection")

    # captured_at is the MATCH date, not the moment we downloaded the file.
    #
    # These are closing odds published after the fact; stamping them with the
    # download time would place a 2020 market in 2026 and make any
    # time-ordered analysis of line movement meaningless.
    captured_at = parse_fd_date(raw.get("_date", "")) or artifact.retrieved_at
    payload = {
        "external_fixture_id": fixture_id,
        "bookmaker": raw.get("bookmaker"),
        "market": raw.get("market", "1x2"),
        "captured_at": captured_at,
        "selections": selections,
    }
    return build_envelope(artifact, confidence=0.9, payload=payload,
                          entity_type="odds_snapshot")
