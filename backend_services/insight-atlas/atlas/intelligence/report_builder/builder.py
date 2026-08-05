"""Composition of deterministic historical intelligence providers."""

from __future__ import annotations

from atlas.intelligence.contracts import AtlasIntelligenceReport
from atlas.intelligence.historical import (
    HistoricalDataset,
    HistoricalScope,
    normalize_key,
)
from atlas.intelligence.orchestrator import AtlasIntelligenceOrchestrator


class HistoricalIntelligenceReportBuilder:
    def __init__(self, dataset: HistoricalDataset) -> None:
        self._dataset = dataset
        self._orchestrator = AtlasIntelligenceOrchestrator(dataset)

    def build(
        self,
        scope: HistoricalScope,
        *,
        home_team: str | None = None,
        away_team: str | None = None,
    ) -> AtlasIntelligenceReport:
        rows = self._dataset.select(scope)
        if not rows:
            raise ValueError("historical_scope_empty")
        query_record = self._query_record(rows, home_team, away_team)
        # STRICTLY prior, and never the analysed match itself. The old
        # `<=` retained `query_record` (which is `rows[-1]`) in its own
        # baseline, so every downstream engine described the match using
        # that match's OWN result — while signal_engine labelled its
        # evidence "leakage-safe form projection". Same policy the
        # hierarchical memory already used
        # (atlas/memory/retrieval_engine/engine.py): a fixture kicking
        # off at the same instant hasn't resolved either, so `<` is the
        # conservative cut.
        rows = [
            row
            for row in rows
            if row.uid != query_record.uid
            and row.kickoff_at < query_record.kickoff_at
        ]
        return self._orchestrator.execute_record(
            query_record,
            rows=rows,
            scope_key=scope.key,
        )

    @staticmethod
    def _query_record(
        rows,
        home_team: str | None,
        away_team: str | None,
    ):
        if home_team is None and away_team is None:
            return rows[-1]
        if not home_team or not away_team:
            raise ValueError("both_teams_required")
        matches = [
            row
            for row in rows
            if normalize_key(row.home) == normalize_key(home_team)
            and normalize_key(row.away) == normalize_key(away_team)
        ]
        if not matches:
            raise ValueError("historical_matchup_empty")
        return matches[-1]
