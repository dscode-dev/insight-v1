"""Record the frozen regression baseline mandated by ATLAS_V1_FROZEN.md.

    Record a real-dataset replay `ReplayManifest` + `ReplayHash` +
    `QualityEvaluation` ... as the frozen baseline; all future replays
    diff against it via the Quality Gate regression report.

Until now that had no implementation at all: `ReplayService` took a
baseline as an in-memory constructor argument, production never passed
one, and nothing could write or read one. This script is the recorder;
`atlas/backtest/baseline.py` is the format.

Usage:
    python -m scripts.atlas_record_baseline \\
        --matches /var/atlas/datasets/<generation>/matches.jsonl \\
        --competition brasileirao_serie_a \\
        --out /var/atlas/baselines/brasileirao_serie_a.json

Then point the service at it with ATLAS_REGRESSION_BASELINE_PATH so every
subsequent replay is diffed against it.

IMPORTANT — record the baseline only AFTER the intelligence changes you
intend to ship are in place. A baseline captured from a build with a
known defect freezes that defect as "correct" and every later replay
will be measured against it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone

from atlas.backtest import ReplayEngine, save_baseline
from atlas.backtest.adapter import scenario_from_scope
from atlas.backtest.manifest import build_manifest
from atlas.intelligence.historical import HistoricalScope, load_dataset


async def run(args) -> None:
    dataset = load_dataset(args.matches, args.projection)
    scope = HistoricalScope(
        competition=args.competition, year=args.year, season=args.season
    )
    scenario = scenario_from_scope(dataset, scope)

    started = datetime.now(timezone.utc)
    result = await ReplayEngine().run(scenario)
    finished = datetime.now(timezone.utc)

    manifest = build_manifest(
        replay_id=f"baseline-{scenario.scenario_id}",
        replay_hash=result.deterministic_hash,
        dataset=scenario.scenario_id,
        competition=args.competition,
        season=args.season or "",
        execution_timestamp=finished,
        execution_duration_ms=int((finished - started).total_seconds() * 1000),
        explorer_dataset_version=args.dataset_version,
        similarity_version=args.similarity_version,
    )
    path = save_baseline(args.out, result=result, manifest=manifest)

    print(json.dumps({
        "baseline": str(path),
        "scenario_id": scenario.scenario_id,
        "replay_hash": result.deterministic_hash,
        "steps_executed": result.steps_executed,
        "trends": len(result.trends),
        "detectors": len(result.detectors),
        "feature_schema_version": manifest.feature_schema_version,
        "similarity_version": manifest.similarity_version,
    }, indent=2))


def main() -> None:
    from atlas.vector_memory.contracts import EMBEDDING_VERSION

    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", required=True, help="path to matches.jsonl")
    parser.add_argument("--projection", help="path to projection.jsonl (defaults to sibling)")
    parser.add_argument("--competition", required=True)
    parser.add_argument("--season")
    parser.add_argument("--year", type=int)
    parser.add_argument("--out", required=True, help="where to write the baseline JSON")
    parser.add_argument("--dataset-version", default="unknown")
    parser.add_argument(
        "--similarity-version", default=EMBEDDING_VERSION,
        help="embedding version this replay ran against (v1 default; pass the v2 "
             "constant when replaying over 37-dim vectors)",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
