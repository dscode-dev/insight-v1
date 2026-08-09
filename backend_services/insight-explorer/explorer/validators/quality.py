"""Deterministic completeness/quality score (Step 9 / QualityScore node).

A 0..1 score from field completeness + entity resolution + trust. Records
below QUALITY_APPROVE_THRESHOLD go to human review (not silently dropped).
The CrewAI Dataset Auditor produces a narrative on top of this number; the
number itself is deterministic and reproducible.

SCORED PER ENTITY TYPE. The weights below describe a FIXTURE — resolved
clubs, a score when finished, a kick-off time. Applying them to a stats or
odds record scores it against fields it is not supposed to have: an odds
snapshot names a bookmaker and no club at all, and would land near 0.1 and
be sent to human review, one row per bookmaker per match.

Each entity type therefore gets its own weights, describing what a complete
record of THAT kind looks like.
"""

from __future__ import annotations

from typing import Any

# (signal, weight). Resolution + score completeness weigh most.
_FIXTURE_WEIGHTS: list[tuple[str, float]] = [
    ("home_resolved", 0.20),
    ("away_resolved", 0.20),
    ("has_score_when_finished", 0.20),
    ("has_venue", 0.10),
    ("has_scheduled_at", 0.10),
    ("has_status_detail", 0.05),
    ("has_short_names", 0.05),
    ("trust", 0.10),
]

# A stats record is complete when it says WHICH match and carries counters
# for both sides. There is no kick-off time or club to resolve in it.
_STATS_WEIGHTS: list[tuple[str, float]] = [
    ("has_fixture_ref", 0.35),
    ("has_home_stats", 0.25),
    ("has_away_stats", 0.25),
    ("trust", 0.15),
]

# An odds snapshot is complete when it says which match, which bookmaker,
# which market, when it was captured, and carries prices.
_ODDS_WEIGHTS: list[tuple[str, float]] = [
    ("has_fixture_ref", 0.25),
    ("has_bookmaker", 0.20),
    ("has_market", 0.15),
    ("has_captured_at", 0.15),
    ("has_selections", 0.15),
    ("trust", 0.10),
]

_TRUST_SCORE = {"high": 1.0, "medium": 0.7, "low": 0.4}


def score(envelope: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """Return (score, breakdown), weighted for the record's entity type."""
    payload = envelope.get("payload") or {}
    trust = _TRUST_SCORE.get(envelope.get("trust_level", "medium"), 0.5)
    entity_type = envelope.get("entity_type") or "fixture"

    if entity_type == "stats":
        signals = _stats_signals(payload, trust)
        weights = _STATS_WEIGHTS
    elif entity_type == "odds_snapshot":
        signals = _odds_signals(payload, trust)
        weights = _ODDS_WEIGHTS
    else:
        signals = _fixture_signals(payload, trust)
        weights = _FIXTURE_WEIGHTS

    breakdown = {name: signals[name] * w for name, w in weights}
    return round(sum(breakdown.values()), 4), breakdown


def _fixture_signals(payload: dict[str, Any], trust: float) -> dict[str, float]:
    home = payload.get("home_team") or {}
    away = payload.get("away_team") or {}
    status = payload.get("status")
    sc = payload.get("score")
    return {
        "home_resolved": 1.0 if home.get("club_id") else 0.0,
        "away_resolved": 1.0 if away.get("club_id") else 0.0,
        "has_score_when_finished": (
            1.0 if (status != "finished" or sc is not None) else 0.0
        ),
        "has_venue": 1.0 if payload.get("venue") else 0.0,
        "has_scheduled_at": 1.0 if payload.get("scheduled_at") else 0.0,
        "has_status_detail": 1.0 if payload.get("status_detail") else 0.0,
        "has_short_names": 1.0 if (home.get("short_name") and away.get("short_name")) else 0.0,
        "trust": trust,
    }


def _stats_signals(payload: dict[str, Any], trust: float) -> dict[str, float]:
    home = payload.get("home") or {}
    away = payload.get("away") or {}
    return {
        "has_fixture_ref": 1.0 if payload.get("external_fixture_id") else 0.0,
        # Non-empty, not merely present: `{}` is a record that says nothing.
        "has_home_stats": 1.0 if home else 0.0,
        "has_away_stats": 1.0 if away else 0.0,
        "trust": trust,
    }


def _odds_signals(payload: dict[str, Any], trust: float) -> dict[str, float]:
    selections = payload.get("selections") or []
    return {
        "has_fixture_ref": 1.0 if payload.get("external_fixture_id") else 0.0,
        "has_bookmaker": 1.0 if payload.get("bookmaker") else 0.0,
        "has_market": 1.0 if payload.get("market") else 0.0,
        "has_captured_at": 1.0 if payload.get("captured_at") else 0.0,
        "has_selections": 1.0 if len(selections) >= 2 else 0.0,
        "trust": trust,
    }
