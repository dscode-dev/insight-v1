"""Dataset manifest builder for a completed/in-progress `Execution`
(ML-D Mission Center) — the shape `execution-detail.tsx` reads at
`GET /explorer/executions/{id}/dataset`.

Only "fixtures" is a real, collected theme today (see catalog.py); odds and
statistics coverage are honestly reported as 0% rather than fabricated,
consistent with the rest of the codebase's "never silently drop, never
invent" discipline (e.g. the Wikipedia adapter yielding no fixtures).
"""

from __future__ import annotations

import time
from typing import Any

from explorer.datalake.lake import DataLake, checksum
from explorer.pipelines.executions.models import Execution
from explorer.pipelines.models import Pipeline


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _count_validated(lake: DataLake, competition: str, season: str, source: str) -> int:
    path = lake.partition("validated", competition, season, source, "fixture")
    if not path.exists():
        return 0
    total = 0
    for f in path.glob("*.jsonl"):
        with f.open("rb") as fh:
            total += sum(1 for _ in fh)
    return total


def build_manifest(execution: Execution, pipeline: Pipeline, lake: DataLake) -> dict[str, Any]:
    enabled_sources = [s.name for s in pipeline.sources if s.enabled]
    seen: set[tuple[str, str]] = set()
    partitions: list[dict[str, Any]] = []
    total_fixtures = 0
    for task in execution.tasks:
        key = (task["competition"], task["season"])
        if key in seen:
            continue
        seen.add(key)
        for source in enabled_sources:
            count = _count_validated(lake, task["competition"], task["season"], source)
            if count:
                partitions.append({"competition": task["competition"], "season": task["season"],
                                   "source": source, "records": count})
                total_fixtures += count

    base = {
        "execution_id": execution.execution_id,
        "pipeline_id": execution.pipeline_id,
        "generation": execution.execution_id,
        "partitions": partitions,
        "totals": {"fixtures": total_fixtures},
        # Honest zeros: no adapter collects odds/statistics yet (see catalog.COLLECTIBLE_THEMES).
        "odds_coverage": {"percentage": 0.0},
        "statistics_coverage": {"percentage": 0.0},
        "generated_at": _now(),
    }
    return {**base, "checksum": checksum(base)}


def build_dataset_view(execution: Execution, pipeline: Pipeline, lake: DataLake) -> dict[str, Any]:
    manifest = build_manifest(execution, pipeline, lake)
    return {
        "generation": manifest["generation"],
        "checksum": manifest["checksum"],
        "odds_coverage": manifest["odds_coverage"],
        "statistics_coverage": manifest["statistics_coverage"],
        "manifest": manifest,
    }
