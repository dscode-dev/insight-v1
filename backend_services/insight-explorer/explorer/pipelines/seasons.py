"""Server-side season resolution (ML-D Mission Center, Decision A-4).

The Console's existing create-pipeline form collects competitions but never
seasons — rather than add an out-of-scope UI field, a pipeline's season
window is derived here from its competition + duration mode: one-shot/custom
→ current season only; recurring → the last 3 seasons including the current
one (loosely mirroring the range the legacy fixed `PLAN` in scheduler.py
hardcoded, without copying its exact per-competition counts).
"""

from __future__ import annotations

import datetime

# Seasons that span a calendar-year boundary (Aug/Sep → May/Jun), formatted
# "YYYY-YYYY" — matches football_data.py's `_season_token` expectation.
_CROSS_YEAR_COMPETITIONS = frozenset({"premier_league", "la_liga", "champions_league"})

# Tournaments that happen every N years rather than annually: anchor year +
# cycle length.
_CYCLIC = {"world_cup": (2018, 4)}


def _cross_year_season(today: datetime.date, offset: int = 0) -> str:
    year = today.year - offset
    if today.month >= 7:
        return f"{year}-{year + 1}"
    return f"{year - 1}-{year}"


def _cyclic_seasons(anchor: int, cycle: int, today_year: int) -> list[str]:
    seasons = []
    year = anchor
    while year <= today_year:
        seasons.append(str(year))
        year += cycle
    return seasons or [str(anchor)]


def resolve_seasons(competition_key: str, duration: dict | None) -> list[str]:
    """Return the season keys a pipeline should collect for one competition,
    given its `duration` config (`{"mode": "one-shot"|"recurring"|"custom", ...}`)."""
    today = datetime.date.today()
    mode = (duration or {}).get("mode", "one-shot")

    if competition_key in _CYCLIC:
        anchor, cycle = _CYCLIC[competition_key]
        cycle_seasons = _cyclic_seasons(anchor, cycle, today.year)
        return cycle_seasons if mode == "recurring" else cycle_seasons[-1:]

    if competition_key in _CROSS_YEAR_COMPETITIONS:
        if mode != "recurring":
            return [_cross_year_season(today)]
        return [_cross_year_season(today, offset) for offset in (2, 1, 0)]

    if mode != "recurring":
        return [str(today.year)]
    return [str(today.year - offset) for offset in (2, 1, 0)]
