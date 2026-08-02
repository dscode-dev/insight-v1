"""Explorer Dataset → Replay adapter (ATLAS-BACKTEST-A2, Stage 1-2).

Reconstructs production `TrendInputs` from real historical Explorer records
(`HistoricalRecord`), then wraps them into a `ReplayScenario` for the existing
ReplayEngine. Every field comes from the record — NOTHING is fabricated and the
production model is not simplified: fields the historical record genuinely does
not carry (live context, odds ticks, live signals, similarity) stay absent, and
the real detectors deterministically return nothing for them, exactly as in
production. All source variants (match / competition / season / interval /
dataset / mission) converge to the SAME builder → the SAME engine.
"""

from __future__ import annotations

from datetime import datetime

from atlas.backtest.contracts import ReplayScenario, ReplayStep
from atlas.intelligence.historical import (
    HistoricalDataset,
    HistoricalRecord,
    HistoricalScope,
    normalize_competition,
    stable_id,
)
from atlas.trends.models import TrendInputs


class ExplorerDatasetAdapter:
    """Deterministic reconstruction of TrendInputs from Explorer history."""

    def record_to_inputs(self, record: HistoricalRecord) -> TrendInputs:
        # Deterministic ids (uuid5) → identical across runs. Real feature vector.
        return TrendInputs(
            canonical_match_id=stable_id("replay-match", record.uid),
            competition_id=stable_id(
                "replay-competition", normalize_competition(record.competition)
            ),
            minute=None,  # completed historical match — no live minute (not fabricated)
            features=dict(record.features) if record.features else None,
        )

    def scenario(
        self,
        records: list[HistoricalRecord],
        *,
        scenario_id: str,
        source: str,
    ) -> ReplayScenario:
        # HistoricalDataset already sorts by (kickoff_at, uid) → deterministic order.
        steps = [
            ReplayStep(index=i, inputs=self.record_to_inputs(record), label=record.uid)
            for i, record in enumerate(records)
        ]
        return ReplayScenario(scenario_id=scenario_id, source=source, steps=steps)


# --------------------------------------------------------------------------- #
# Source variants — all converge to ExplorerDatasetAdapter.scenario (no dupes).
# --------------------------------------------------------------------------- #
def scenario_from_scope(
    dataset: HistoricalDataset,
    scope: HistoricalScope,
    *,
    adapter: ExplorerDatasetAdapter | None = None,
    source: str = "competition",
) -> ReplayScenario:
    adapter = adapter or ExplorerDatasetAdapter()
    records = dataset.select(scope)
    return adapter.scenario(records, scenario_id=f"scope:{scope.key}", source=source)


def scenario_from_match(
    dataset: HistoricalDataset,
    uid: str,
    *,
    adapter: ExplorerDatasetAdapter | None = None,
) -> ReplayScenario:
    adapter = adapter or ExplorerDatasetAdapter()
    records = [r for r in dataset.records if r.uid == uid]
    return adapter.scenario(records, scenario_id=f"match:{uid}", source="match")


def scenario_from_season(
    dataset: HistoricalDataset,
    competition: str,
    season: str,
    *,
    adapter: ExplorerDatasetAdapter | None = None,
) -> ReplayScenario:
    return scenario_from_scope(
        dataset,
        HistoricalScope(competition=competition, season=season),
        adapter=adapter,
        source="season",
    )


def scenario_from_interval(
    dataset: HistoricalDataset,
    competition: str,
    start: datetime,
    end: datetime,
    *,
    adapter: ExplorerDatasetAdapter | None = None,
) -> ReplayScenario:
    adapter = adapter or ExplorerDatasetAdapter()
    comp = normalize_competition(competition)
    records = [
        r
        for r in dataset.records
        if normalize_competition(r.competition) == comp and start <= r.kickoff_at < end
    ]
    return adapter.scenario(
        records,
        scenario_id=f"interval:{comp}:{start.isoformat()}:{end.isoformat()}",
        source="interval",
    )


def scenario_from_dataset(
    dataset: HistoricalDataset,
    *,
    adapter: ExplorerDatasetAdapter | None = None,
    scenario_id: str = "dataset:all",
) -> ReplayScenario:
    adapter = adapter or ExplorerDatasetAdapter()
    return adapter.scenario(list(dataset.records), scenario_id=scenario_id, source="dataset")


def scenario_from_mission(
    dataset: HistoricalDataset,
    competition: str,
    season: str | None = None,
    *,
    adapter: ExplorerDatasetAdapter | None = None,
) -> ReplayScenario:
    # An Explorer mission collects a competition (± season) worth of history; it
    # maps onto the same scope selection — no separate replay path.
    return scenario_from_scope(
        dataset,
        HistoricalScope(competition=competition, season=season),
        adapter=adapter,
        source="mission",
    )
