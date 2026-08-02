"""Deterministic completeness/quality score (Step 9 / QualityScore node).

A 0..1 score from field completeness + entity resolution + trust. Records
below QUALITY_APPROVE_THRESHOLD go to human review (not silently dropped).
The CrewAI Dataset Auditor produces a narrative on top of this number; the
number itself is deterministic and reproducible.
"""

from __future__ import annotations

from typing import Any

# (field path, weight). Resolution + score completeness weigh most.
_WEIGHTS: list[tuple[str, float]] = [
    ("home_resolved", 0.20),
    ("away_resolved", 0.20),
    ("has_score_when_finished", 0.20),
    ("has_venue", 0.10),
    ("has_scheduled_at", 0.10),
    ("has_status_detail", 0.05),
    ("has_short_names", 0.05),
    ("trust", 0.10),
]

_TRUST_SCORE = {"high": 1.0, "medium": 0.7, "low": 0.4}


def score(envelope: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """Return (score, breakdown)."""
    payload = envelope.get("payload") or {}
    home = payload.get("home_team") or {}
    away = payload.get("away_team") or {}
    status = payload.get("status")
    sc = payload.get("score")

    signals = {
        "home_resolved": 1.0 if home.get("club_id") else 0.0,
        "away_resolved": 1.0 if away.get("club_id") else 0.0,
        "has_score_when_finished": (
            1.0 if (status != "finished" or sc is not None) else 0.0
        ),
        "has_venue": 1.0 if payload.get("venue") else 0.0,
        "has_scheduled_at": 1.0 if payload.get("scheduled_at") else 0.0,
        "has_status_detail": 1.0 if payload.get("status_detail") else 0.0,
        "has_short_names": 1.0 if (home.get("short_name") and away.get("short_name")) else 0.0,
        "trust": _TRUST_SCORE.get(envelope.get("trust_level", "medium"), 0.5),
    }
    breakdown = {name: signals[name] * w for name, w in _WEIGHTS}
    return round(sum(breakdown.values()), 4), breakdown
