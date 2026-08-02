"""Deterministic consistency checks (Step 9 / ConsistencyCheck node).

Rules that don't need a schema but encode football reality. Violations are
returned as rule names; the pipeline decides reject vs human-review. The
CrewAI Match Validator reasons about *ambiguous* cases — these hard rules
run first and always.
"""

from __future__ import annotations

from typing import Any


def check(envelope: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    payload = envelope.get("payload") or {}

    home = (payload.get("home_team") or {}).get("name")
    away = (payload.get("away_team") or {}).get("name")
    if home and away and home == away:
        violations.append("same_team_both_sides")

    status = payload.get("status")
    score = payload.get("score")
    if status == "finished" and score is None:
        violations.append("finished_without_score")

    if score is not None:
        for side in ("home", "away"):
            val = score.get(side)
            if val is not None and (val < 0 or val > 30):
                violations.append(f"implausible_score_{side}")
        ht_h, ht_a = score.get("halftime_home"), score.get("halftime_away")
        if ht_h is not None and score.get("home") is not None and ht_h > score["home"]:
            violations.append("halftime_exceeds_fulltime_home")
        if ht_a is not None and score.get("away") is not None and ht_a > score["away"]:
            violations.append("halftime_exceeds_fulltime_away")

    if status == "scheduled" and score is not None:
        violations.append("scheduled_with_score")

    return violations
