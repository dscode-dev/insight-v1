"""Pure pipeline-draft estimator (ML-D Mission Center).

No network calls, no side effects — a deterministic function of a draft
config, called live as the operator edits the create form (debounced on the
Console side). Only "fixtures" is a collectible theme today (see
catalog.py); a draft with no collectible theme selected estimates to zero
work rather than fabricating a number for collection that won't happen.
"""

from __future__ import annotations

from typing import Any

from explorer.config import COLLECTOR
from explorer.pipelines.catalog import COLLECTIBLE_THEMES
from explorer.pipelines.seasons import resolve_seasons

# Rough requests-per-(competition,season) job, from each adapter's real fetch
# pattern: ESPN issues one request per day in the collection window; the
# others fetch a single page/file per season.
_REQUESTS_PER_JOB = {"espn": 250, "fbref": 1, "football_data": 1, "wikipedia": 1}
_DEFAULT_REQUESTS_PER_JOB = 5
_SECONDS_PER_REQUEST_OVERHEAD = 0.5  # assumed round-trip, on top of the polite delay


def _warnings(sources: list[dict], competitions: list[str], themes: list[str], collectible: bool) -> list[str]:
    warnings: list[str] = []
    if not sources:
        warnings.append("no enabled sources selected")
    if not competitions:
        warnings.append("no competitions selected")
    if not themes:
        warnings.append("no themes selected")
    elif not collectible:
        warnings.append("no collectible theme selected — only 'fixtures' is collected today; "
                        "the rest are declared scope for future collectors")
    non_collectible = sorted(set(themes) - COLLECTIBLE_THEMES)
    if non_collectible and collectible:
        warnings.append(f"themes {non_collectible} are declared but not yet collected")
    return warnings


def estimate(draft: dict[str, Any]) -> dict[str, Any]:
    sources = [s for s in (draft.get("sources") or []) if s.get("enabled", True)]
    competitions = list(draft.get("competitions") or [])
    themes = list(draft.get("themes") or [])
    collectible = bool(set(themes) & COLLECTIBLE_THEMES)
    warnings = _warnings(sources, competitions, themes, collectible)

    if not collectible or not sources or not competitions:
        return {"source_jobs": 0, "estimated_requests": 0, "estimated_runtime_hours": 0.0,
                "warnings": warnings}

    duration = draft.get("duration") or {"mode": "one-shot"}
    seasons_per_competition = {c: resolve_seasons(c, duration) for c in competitions}
    source_jobs = sum(len(seasons) for seasons in seasons_per_competition.values()) * len(sources)

    avg_requests_per_job = sum(
        _REQUESTS_PER_JOB.get(s["name"], _DEFAULT_REQUESTS_PER_JOB) for s in sources
    ) / len(sources)
    estimated_requests = int(source_jobs * avg_requests_per_job)
    seconds_per_request = COLLECTOR.polite_delay_s + _SECONDS_PER_REQUEST_OVERHEAD
    estimated_runtime_hours = round(estimated_requests * seconds_per_request / 3600, 2)

    return {
        "source_jobs": source_jobs,
        "estimated_requests": estimated_requests,
        "estimated_runtime_hours": estimated_runtime_hours,
        "warnings": warnings,
    }
