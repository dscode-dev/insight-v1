"""ML-B target job: Brasileirão Série A, seasons 2020–2024 (Step 1/14).

Adding another competition is a one-line change here (plus its COMPETITIONS
row) — no collector/pipeline change, satisfying Step 1's extensibility rule.
"""

from __future__ import annotations

from explorer.adapters.espn import ESPNAdapter
from explorer.jobs.runner import JobRecord, JobRunner

BRASILEIRAO_SEASONS = ("2020", "2021", "2022", "2023", "2024")


def run_brasileirao(
    runner: JobRunner | None = None, seasons: tuple[str, ...] = BRASILEIRAO_SEASONS
) -> list[JobRecord]:
    runner = runner or JobRunner()
    adapter = ESPNAdapter()
    records: list[JobRecord] = []
    consecutive_failures = 0
    for season in seasons:
        rec = runner.run(adapter, "brasileirao_serie_a", season)
        records.append(rec)
        if rec.status in {"failed", "skipped"}:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                runner.tickets.open(
                    error_type="job_repeated_failure", source=adapter.name,
                    competition="brasileirao_serie_a", season=season, entity_type="fixture",
                    severity="high")
        else:
            consecutive_failures = 0
    runner.tickets.flush()
    return records
