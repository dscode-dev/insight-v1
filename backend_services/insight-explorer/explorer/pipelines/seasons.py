"""Server-side season resolution (ML-D Mission Center, Decision A-4).

The Console's existing create-pipeline form collects competitions but never
seasons — rather than add an out-of-scope UI field, a pipeline's season
window is derived here from its competition + duration mode:

    one-shot   → the current season only
    recurring  → the last 3 seasons, including the current one
    custom     → an explicit list, or a count of seasons back

`custom` was declared in the catalog and did nothing: it fell through to the
one-shot branch, so a pipeline asking for a custom window silently collected
one season. It is implemented here because a five-year backfill has no other
way to be expressed — `recurring` caps at three.
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
    duration = duration or {}
    mode = duration.get("mode", "one-shot")

    if mode == "custom":
        return _custom_seasons(competition_key, duration, today)

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


def _custom_seasons(competition_key: str, duration: dict, today: datetime.date) -> list[str]:
    """An explicit `seasons` list, or `years` seasons back from the current one.

    `seasons` wins when both are given: an operator who typed the labels meant
    those labels, and quietly overriding them with a count would collect a
    different window than the one on screen.

    An explicit list is NOT validated against what a source carries. Coverage
    is the adapter's to answer — `fetch_season` returns nothing for a season
    it does not have — and rejecting here would mean this module needed to
    know every source's catalogue.
    """
    explicit = duration.get("seasons")
    if isinstance(explicit, list) and explicit:
        return [str(s) for s in explicit if str(s).strip()]

    try:
        years = int(duration.get("years", 0))
    except (TypeError, ValueError):
        years = 0
    if years <= 0:
        # A custom window with neither list nor count is a half-filled form.
        # Falling back to the current season keeps the pipeline runnable and
        # matches what the mode did before it was implemented.
        years = 1

    if competition_key in _CYCLIC:
        anchor, cycle = _CYCLIC[competition_key]
        return _cyclic_seasons(anchor, cycle, today.year)[-years:]
    if competition_key in _CROSS_YEAR_COMPETITIONS:
        return [_cross_year_season(today, offset) for offset in range(years - 1, -1, -1)]
    return [str(today.year - offset) for offset in range(years - 1, -1, -1)]
