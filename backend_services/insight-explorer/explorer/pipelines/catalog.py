"""Auto-recommended pipeline defaults (ML-D Mission Center).

The Console's create-pipeline form must arrive pre-filled with sensible
choices, not a blank slate — the operator only adjusts or adds. This module
is the single source of truth for what "sensible" means, derived from the
real adapter registry and competition registry rather than duplicated
literals in the frontend.
"""

from __future__ import annotations

import datetime
from typing import Any

from explorer.config import COMPETITIONS
from explorer.sources import build_default_registry

# Entity-type themes with a real, working collector today. Every theme has a
# contract (`contracts/explorer.<theme singular>.v1.json`) but only fixtures
# are actually produced by an adapter+normalizer pair — see estimate.py,
# which only counts collectible themes, and engine.py, which only schedules
# tasks for them. Declaring the rest keeps the catalog honest about the
# platform's target shape without fabricating collection capability.
THEMES: tuple[str, ...] = ("fixtures", "odds", "lineups", "injuries", "stats")
COLLECTIBLE_THEMES: frozenset[str] = frozenset({"fixtures"})

DURATIONS: tuple[str, ...] = ("one-shot", "recurring", "custom")

_RECOMMENDED_SOURCE_ORDER = ("espn", "football_data", "fbref", "wikipedia")
_DEFAULT_WEIGHT_PRIORITY = {
    "high": 1.0,
    "medium": 0.7,
    "low": 0.4,
}


def _recent_seasons(count: int = 5) -> list[str]:
    year = datetime.date.today().year
    return [str(y) for y in range(year - count + 1, year + 1)]


def build_catalog() -> dict[str, Any]:
    registry = build_default_registry()
    by_name = {a.name: a for a in registry}
    ordered_names = [n for n in _RECOMMENDED_SOURCE_ORDER if n in by_name]
    ordered_names += [n for n in by_name if n not in ordered_names]

    sources = []
    recommended_sources = []
    for priority, name in enumerate(ordered_names, start=1):
        adapter = by_name[name]
        trust = getattr(adapter, "trust_level", "medium")
        sources.append({"name": name, "trust_level": trust, "priority": priority})
        if trust in ("high", "medium"):
            recommended_sources.append(
                {"name": name, "enabled": True,
                 "weight": _DEFAULT_WEIGHT_PRIORITY.get(trust, 0.5), "priority": priority})

    competitions = [
        {"key": key, "name": comp.name, "seasons": _recent_seasons()}
        for key, comp in COMPETITIONS.items()
    ]
    recommended_competitions = [c.competition_key for c in COMPETITIONS.values()][:1]

    return {
        "sources": sources,
        "competitions": competitions,
        "themes": list(THEMES),
        "durations": list(DURATIONS),
        "recommended": {
            "sources": recommended_sources,
            "competitions": recommended_competitions,
            "themes": ["fixtures"],
            "duration": {"mode": "one-shot"},
            "schedule": None,
        },
    }
