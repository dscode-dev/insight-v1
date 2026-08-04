"""One-time idempotent migration: the legacy fixed `Scheduler`/`PLAN`
(explorer/scheduler.py) becomes a `Pipeline` (type=historical,
duration=recurring) the operator can see, edit and control from Mission
Center, instead of an invisible hardcoded loop. Already-collected
(competition, season) pairs are read from `reports/scheduler_state.json` (if
present) and marked done on the seeded `Execution` so nothing re-collects.
"""

from __future__ import annotations

import json
import time
from typing import Any

from explorer.datalake.lake import DataLake
from explorer.pipelines.executions.models import Execution
from explorer.pipelines.executions.store import ExecutionStore
from explorer.pipelines.models import Pipeline, PipelineSource
from explorer.pipelines.store import PipelineNotFound, PipelineStore
from explorer.scheduler import PLAN

DEFAULT_PIPELINE_ID = "default-historical-plan"
DEFAULT_EXECUTION_ID = "default-historical-plan-seed"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_legacy_completed(lake: DataLake) -> set[tuple[str, str]]:
    path = lake.root / "reports" / "scheduler_state.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return set()
    return {tuple(t) for t in data.get("completed", [])}


def seed_default_pipeline(
    lake: DataLake, pipeline_store: PipelineStore | None = None,
    execution_store: ExecutionStore | None = None,
) -> Pipeline | None:
    """Returns the seeded Pipeline, or None if migration already ran
    (idempotent — safe to call on every startup)."""
    pipeline_store = pipeline_store or PipelineStore(lake.root)
    execution_store = execution_store or ExecutionStore(lake.root)
    try:
        pipeline_store.get(DEFAULT_PIPELINE_ID)
        return None
    except PipelineNotFound:
        pass

    competitions = sorted({c for c, _ in PLAN})
    pipeline = Pipeline(
        pipeline_id=DEFAULT_PIPELINE_ID,
        name="Default historical plan (migrated)",
        description="Auto-migrated from the legacy fixed Scheduler PLAN so continuous "
                    "collection continues under Mission Center instead of an invisible loop.",
        type="historical", owner="system",
        sources=[PipelineSource("espn", priority=1), PipelineSource("fbref", priority=2),
                 PipelineSource("football_data", priority=3), PipelineSource("wikipedia", priority=4)],
        competitions=competitions, themes=["fixtures"],
        duration={"mode": "recurring"}, schedule=None,
    )
    pipeline_store.create(pipeline)

    completed = _load_legacy_completed(lake)
    tasks: list[dict[str, Any]] = [
        {"competition": c, "season": s, "status": "done" if (c, s) in completed else "pending"}
        for c, s in PLAN
    ]
    jobs_completed = sum(1 for t in tasks if t["status"] == "done")
    execution = Execution(
        pipeline_id=DEFAULT_PIPELINE_ID, pipeline_name=pipeline.name, execution_id=DEFAULT_EXECUTION_ID,
        state="completed" if jobs_completed == len(tasks) else "pending",
        jobs_total=len(tasks), jobs_completed=jobs_completed, jobs_remaining=len(tasks) - jobs_completed,
        progress=round(jobs_completed / len(tasks), 4) if tasks else 1.0,
        source_count=len(pipeline.sources), tasks=tasks,
        created_at=_now(),
    )
    execution_store.create(execution)
    return pipeline
