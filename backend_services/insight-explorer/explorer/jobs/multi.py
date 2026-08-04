"""Multi-source job (ML-B.5).

For one (competition, season): run every registered source that supports it
through the normal JobRunner (source-isolated, raw preserved, AI pipeline),
then reconcile across sources to record source confidence. Sources that have
no coverage for the competition simply contribute nothing — the framework is
real even when only one source carries a given competition.
"""

from __future__ import annotations

from typing import Any

from explorer.datalake.lake import DataLake
from explorer.jobs.reconcile import reconcile
from explorer.jobs.runner import JobRunner
from explorer.observability.logging import get_logger
from explorer.sources import adapters_for, build_default_registry

_log = get_logger("explorer.multi")


def run_multi_source(competition: str, season: str, runner: JobRunner | None = None,
                     registry: list[Any] | None = None,
                     allowed_sources: set[str] | None = None,
                     execution_id: str = "") -> dict[str, Any]:
    """`allowed_sources`, when given, further restricts collection to that
    set of adapter names on top of the usual coverage/enabled filtering — the
    Mission Center's per-pipeline source scope (a pipeline may deliberately
    use fewer sources than are globally enabled)."""
    from explorer.ops import runtime_config

    runner = runner or JobRunner()
    registry = registry if registry is not None else build_default_registry()
    lake: DataLake = runner.lake
    cfg = runtime_config.load(lake.root)
    adapters = [a for a in adapters_for(competition, registry) if cfg.source_enabled(a.name)]
    if allowed_sources is not None:
        adapters = [a for a in adapters if a.name in allowed_sources]

    per_source = []
    contributing = []
    for adapter in adapters:
        rec = runner.run(adapter, competition, season, execution_id=execution_id)
        per_source.append({
            "source": adapter.name, "status": rec.status,
            "collected": rec.records_collected, "validated": rec.records_validated,
            "review": rec.records_review, "rejected": rec.records_rejected,
            "job_id": rec.job_id,
        })
        if rec.records_validated > 0:
            contributing.append(adapter.name)

    reconciliation = reconcile(competition, season, contributing or [a.name for a in adapters], lake)
    result = {
        "competition": competition, "season": season,
        "sources_run": [a.name for a in adapters],
        "contributing_sources": contributing,
        "per_source": per_source,
        "reconciliation": reconciliation,
    }
    runner.tickets.flush()
    _log.info("multi_source_done", competition=competition, season=season,
              contributing=contributing, total_validated=sum(s["validated"] for s in per_source))
    return result
