"""Dependency-aware execution of the Atlas intelligence engines."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import TYPE_CHECKING

from atlas.intelligence.behavior_engine import BehavioralPatternEngine
from atlas.intelligence.contracts import (
    AtlasIntelligenceReport,
    Evidence,
    EvidenceType,
)
from atlas.intelligence.evidence_engine import EvidenceEngine
from atlas.intelligence.historical import (
    HistoricalDataset,
    HistoricalRecord,
    normalize_competition,
    normalize_key,
    stable_id,
    summarize,
)
from atlas.intelligence.kernel import InsightID
from atlas.intelligence.market_engine import MarketIntelligenceEngine
from atlas.intelligence.orchestrator.context import (
    AtlasRuntimeContext,
    RuntimeExecutionTrace,
)
from atlas.intelligence.reasoning_engine import DeterministicReasoningEngine
from atlas.intelligence.regime_engine import HistoricalRegimeEngine
from atlas.intelligence.signal_engine import HistoricalSignalEngine
from atlas.intelligence.signal_state_engine import SignalStateEngine
from atlas.intelligence.similarity_engine import HistoricalMemory, SimilarityEngine
from atlas.intelligence.trend_engine import HistoricalTrendEngine
from atlas.intelligence.uncertainty_engine import UncertaintyEngine
from atlas.memory import HierarchicalMemoryRetrievalEngine

# atlas.strength.formulas is a leaf module (no atlas.intelligence
# dependency) — safe to import directly at module level. The package's
# __init__ (atlas.strength) pulls in atlas.intelligence.historical via
# lake.py, which would otherwise cycle back here; MarketFeatures/
# TeamStrengthFeatures are therefore TYPE_CHECKING-only (they're already
# used as forward-ref string annotations below, never at runtime).
from atlas.strength.formulas import line_movement as _line_movement_delta
from atlas.vector_memory import (
    DeterministicEmbeddingEncoder,
    DeterministicVectorIndex,
    VectorConfidence,
)

if TYPE_CHECKING:
    from atlas.strength import MarketFeatures, TeamStrengthFeatures

ENGINE_ORDER = [
    "evidence_engine",
    "market_engine",
    "uncertainty_preflight",
    "signal_engine",
    "signal_state_engine",
    "trend_engine",
    "memory_engine",
    "similarity_engine",
    "behavior_engine",
    "uncertainty_finalizer",
    "reasoning_engine",
    "vector_memory_engine",
    "report_builder",
]
RUNTIME_SIMILARITY_THRESHOLD = 0.75


class AtlasIntelligenceOrchestrator:
    def __init__(
        self,
        dataset: HistoricalDataset,
        vector_index: DeterministicVectorIndex | None = None,
    ) -> None:
        self._dataset = dataset
        self._evidence = EvidenceEngine()
        self._market = MarketIntelligenceEngine(self._evidence)
        self._uncertainty = UncertaintyEngine()
        self._signals = HistoricalSignalEngine(self._evidence)
        self._signal_state = SignalStateEngine(self._evidence)
        self._trends = HistoricalTrendEngine(self._evidence)
        self._regime = HistoricalRegimeEngine()
        self._memory = HierarchicalMemoryRetrievalEngine(dataset, self._evidence)
        self._similarity = SimilarityEngine(
            HistoricalMemory(dataset), self._evidence
        )
        self._behaviors = BehavioralPatternEngine(self._evidence)
        self._reasoning = DeterministicReasoningEngine()
        self._vector_index = vector_index
        self._embedding = DeterministicEmbeddingEncoder()

    def execute(
        self,
        context: AtlasRuntimeContext,
        *,
        strength_features: TeamStrengthFeatures | None = None,
        market_features: MarketFeatures | None = None,
    ) -> AtlasIntelligenceReport:
        """`strength_features`/`market_features` are precomputed by the
        caller (an async route handler — see
        `intelligence_workspace.py::_runtime_report`) since they require
        async DB reads (`atlas.strength.StrengthRepository`,
        `atlas.strength.market_features_for_match`) this orchestrator
        itself stays synchronous for. Both are optional: absent means
        "no live state available yet" (cold start, DB not wired in a
        given deployment), and `_runtime_query` degrades gracefully —
        never fabricates a value."""
        competition = normalize_competition(context.competition)
        competition_rows = [
            row
            for row in self._dataset.records
            if normalize_competition(row.competition) == competition
        ]
        if not competition_rows:
            raise ValueError("historical_scope_empty")
        as_of = context.as_of or (
            competition_rows[-1].kickoff_at + timedelta(seconds=1)
        )
        rows = [row for row in competition_rows if row.kickoff_at < as_of]
        if not rows:
            raise ValueError("historical_scope_empty")
        query = self._runtime_query(
            context, rows, as_of, strength_features, market_features
        )
        return self.execute_record(
            query,
            rows=rows,
            scope_key=(
                f"runtime:{competition}:{normalize_key(context.home_team)}:"
                f"{normalize_key(context.away_team)}:{as_of.isoformat()}"
            ),
            requested_regime=context.regime,
            runtime_context=context,
        )

    def execute_record(
        self,
        query: HistoricalRecord,
        *,
        rows: list[HistoricalRecord],
        scope_key: str,
        requested_regime=None,
        runtime_context: AtlasRuntimeContext | None = None,
    ) -> AtlasIntelligenceReport:
        rows = [row for row in rows if row.kickoff_at <= query.kickoff_at]
        if not rows:
            raise ValueError("historical_scope_empty")
        completed = ["evidence_engine"]
        stats = summarize(rows)
        regime = self._regime.classify(
            rows, competition=query.competition, scope_key=scope_key
        )
        if requested_regime is not None and requested_regime != regime.regime_type:
            raise ValueError("regime_mismatch")

        if runtime_context and runtime_context.odds:
            market, market_evidence = self._market.analyze_runtime_odds(
                runtime_context.odds.model_dump(),
                scope_key=scope_key,
                as_of=query.kickoff_at,
            )
        else:
            market, market_evidence = self._market.analyze(
                rows, scope_key=scope_key, as_of=query.kickoff_at
            )
        completed.append("market_engine")

        disagreement = market.disagreement if market else 0.0
        pressure = market.favorite_pressure if market else 0.0
        conflicts = []
        if market and pressure >= 0.65 and disagreement >= 0.5:
            conflicts.append("favorite pressure conflicts with market disagreement")
        uncertainty = self._uncertainty.assess(
            scope_key=scope_key,
            sample_size=len(rows),
            odds_coverage=1.0 if runtime_context and runtime_context.odds else stats["odds_coverage"],
            source_count=stats["source_count"],
            market_disagreement=disagreement,
            conflicting_signals=conflicts,
            unavailable_signals=["comeback tendency"],
            created_at=query.kickoff_at,
        )
        completed.append("uncertainty_preflight")

        signals = self._signals.generate(
            rows,
            scope_key=scope_key,
            as_of=query.kickoff_at,
            report_uncertainty=uncertainty,
            market_disagreement=disagreement,
            favorite_pressure=pressure,
        )
        completed.append("signal_engine")
        signal_state = self._signal_state.evaluate(
            signals,
            scope_key=scope_key,
            as_of=query.kickoff_at,
        )
        completed.append("signal_state_engine")
        trends = self._trends.detect(
            rows,
            scope_key=scope_key,
            as_of=query.kickoff_at,
            regime=regime,
        )
        completed.append("trend_engine")
        memory = self._memory.retrieve(
            query, minimum_similarity=RUNTIME_SIMILARITY_THRESHOLD
        )
        completed.append("memory_engine")
        similarity = self._similarity.analyze(
            query,
            signals=signals,
            market=market,
            regime=regime,
            trends=trends,
            scope_key=scope_key,
            limit=100,
            minimum_score=RUNTIME_SIMILARITY_THRESHOLD,
        )
        completed.append("similarity_engine")
        behaviors = self._behaviors.detect(
            signals=signals,
            signal_states=signal_state.states,
            trends=trends,
            regime=regime,
            similarity=similarity,
            market=market,
            uncertainty=uncertainty,
            scope_key=scope_key,
        )
        completed.append("behavior_engine")

        memory_conflict = []
        if memory.memory_confidence.uncertainty >= 0.5:
            memory_conflict.append("hierarchical memory coverage is limited")
        final_uncertainty = self._uncertainty.assess(
            scope_key=f"{scope_key}:final",
            sample_size=len(rows),
            odds_coverage=1.0 if runtime_context and runtime_context.odds else stats["odds_coverage"],
            source_count=stats["source_count"],
            market_disagreement=disagreement,
            conflicting_signals=[
                *conflicts,
                *memory_conflict,
                *signal_state.conflicting_signals,
            ],
            unavailable_signals=[
                "comeback tendency",
                *signal_state.expired_signals,
            ],
            created_at=query.kickoff_at,
        )
        completed.append("uncertainty_finalizer")

        regime_evidence = self._evidence.create(
            scope_key=scope_key,
            evidence_type=EvidenceType.regime,
            source="competition and historical runtime context",
            description=(
                f"{query.competition} classified as {regime.regime_type.value} "
                f"from {len(rows)} strictly prior matches"
            ),
            observed_at=query.kickoff_at,
            weight=0.85,
            confidence=regime.confidence,
            attributes={"competition": query.competition, "strictly_prior": True},
        )
        evidence = _unique(
            [
                *market_evidence,
                regime_evidence,
                *signal_state.evidence,
                *(item for signal in signals for item in signal.evidence),
                *(item for trend in trends for item in trend.evidence),
                *memory.evidence,
                *similarity.evidence,
                *(item for pattern in behaviors for item in pattern.evidence),
            ]
        )
        reasoning = self._reasoning.analyze(
            signals=signals,
            evidence=evidence,
            trends=trends,
            regime=regime,
            market=market,
            memory=memory,
            similarity=similarity,
            behaviors=behaviors,
            uncertainty=final_uncertainty,
            scope_key=scope_key,
            signal_states=signal_state.states,
        )
        completed.append("reasoning_engine")
        preliminary = AtlasIntelligenceReport(
            report_id=InsightID(stable_id(scope_key, query.uid, "runtime-report")),
            match_id=stable_id("match", query.uid),
            competition_id=stable_id("competition", query.competition),
            as_of=query.kickoff_at,
            signals=signals,
            signal_states=signal_state.states,
            signal_state=signal_state,
            strongest_signals=signal_state.strongest_signals,
            weakest_signals=signal_state.weakest_signals,
            expired_signals=signal_state.expired_signals,
            conflicting_signals=signal_state.conflicting_signals,
            reinforced_signals=signal_state.reinforced_signals,
            dependency_explanation=signal_state.dependency_explanation,
            evidence=evidence,
            trends=trends,
            regime=regime,
            market=market,
            head_to_head=memory.head_to_head,
            home_team_memory=memory.home_team_memory,
            away_team_memory=memory.away_team_memory,
            memory_confidence=memory.memory_confidence,
            memory=memory,
            similarity=similarity,
            behaviors=behaviors,
            patterns=[pattern.type.value for pattern in behaviors],
            reasoning=reasoning.reasoning,
            graph=reasoning.graph,
            conflicts=reasoning.conflicts,
            confidence_explanation=reasoning.confidence,
            uncertainty_explanation=reasoning.uncertainty,
            uncertainty=final_uncertainty,
            created_at=query.kickoff_at,
        )
        if self._vector_index is not None:
            vector = self._vector_index.search(
                self._embedding.from_report(preliminary)
            )
        else:
            vector = _empty_vector()
        completed.append("vector_memory_engine")
        completed.append("report_builder")
        trace = RuntimeExecutionTrace(
            engine_order=ENGINE_ORDER,
            completed_engines=completed,
            request_odds_used=bool(runtime_context and runtime_context.odds),
            historical_data=(
                runtime_context.historical_data
                if runtime_context
                else "certified_historical_scope"
            ),
        )
        return preliminary.model_copy(
            update={
                "vector_contexts": vector.contexts,
                "vector_neighbors": vector.neighbor_count,
                "vector_confidence": vector.confidence,
                "runtime": trace,
            }
        )

    @staticmethod
    def _runtime_query(
        context: AtlasRuntimeContext,
        rows: list[HistoricalRecord],
        as_of,
        strength: TeamStrengthFeatures | None = None,
        market: MarketFeatures | None = None,
    ) -> HistoricalRecord:
        home_key = normalize_key(context.home_team)
        away_key = normalize_key(context.away_team)
        home_rows = [
            row for row in rows if home_key in {normalize_key(row.home), normalize_key(row.away)}
        ]
        away_rows = [
            row for row in rows if away_key in {normalize_key(row.home), normalize_key(row.away)}
        ]
        features = {
            "home_points_5": _team_feature(home_rows, context.home_team, "points"),
            "away_points_5": _team_feature(away_rows, context.away_team, "points"),
            "elo_difference": _elo_difference(
                home_rows, away_rows, home_key, away_key
            ),
            "draw_rate_mean_5": _recent_draw_rate(home_rows, away_rows),
            "expected_total_goals_5": _recent_goals(home_rows, away_rows),
            "prior_matches": float(min(len(home_rows), len(away_rows))),
        }
        sources = {"runtime-context"}
        if context.odds:
            odds = context.odds
            current = [odds.current_home, odds.current_draw, odds.current_away]
            probabilities = _normalise([1.0 / value for value in current])
            opening = [odds.opening_home, odds.opening_draw, odds.opening_away]
            opening_probabilities = _normalise([1.0 / value for value in opening])
            features.update(
                {
                    "odds_available": 1.0,
                    "opening_home": odds.opening_home,
                    "opening_draw": odds.opening_draw,
                    "opening_away": odds.opening_away,
                    "closing_home": odds.current_home,
                    "closing_draw": odds.current_draw,
                    "closing_away": odds.current_away,
                    "favorite_strength": max(probabilities),
                    "market_entropy": min(
                        1.0,
                        -sum(
                            probability * math.log(probability)
                            for probability in probabilities
                        )
                        / math.log(3),
                    ),
                }
            )
            movement = _line_movement_delta(opening_probabilities[0], probabilities[0])
            if movement is not None:
                features["line_movement"] = movement
            sources.add(context.odds.bookmaker or "runtime-odds")
        elif market is not None and market.market_available:
            # No odds supplied directly in the request — fall back to
            # Atlas's own persisted odds-tick history (atlas.odds_ticks,
            # populated live off the Hub's match.odds stream) rather
            # than leaving the market dimension unavailable.
            features["odds_available"] = 1.0
            if market.market_pressure is not None:
                features["favorite_strength"] = market.market_pressure
            if market.market_entropy is not None:
                features["market_entropy"] = market.market_entropy
            if market.line_movement is not None:
                features["line_movement"] = market.line_movement
            sources.add("odds-ticks")
        else:
            features["odds_available"] = 0.0

        if strength is not None:
            # Live team-strength state (Elo/attack-defense/h2h/standings/
            # rest) — overrides the thinner "most recent historical row"
            # approximation above with Atlas's own incrementally-updated
            # state (atlas/strength/). Optional sub-fields stay absent
            # (never fabricated as 0.0) when there isn't enough history.
            features["elo_difference"] = strength.elo_delta
            features["home_attack_strength"] = strength.home_attack_strength
            features["away_attack_strength"] = strength.away_attack_strength
            features["home_defense_strength"] = strength.home_defense_strength
            features["away_defense_strength"] = strength.away_defense_strength
            if strength.h2h_advantage is not None:
                features["h2h_advantage"] = strength.h2h_advantage
            if strength.table_position_gap is not None:
                features["table_position_gap"] = strength.table_position_gap
            if strength.rest_advantage is not None:
                features["rest_advantage"] = strength.rest_advantage
            sources.add("team-strength-state")

        uid = str(
            stable_id(
                "runtime-query",
                normalize_competition(context.competition),
                home_key,
                away_key,
                as_of.isoformat(),
            )
        )
        return HistoricalRecord(
            uid=uid,
            competition=normalize_competition(context.competition),
            season="runtime",
            kickoff_at=as_of,
            home=home_key,
            away=away_key,
            home_score=0,
            away_score=0,
            label="",
            sources=tuple(sorted(sources)),
            features=features,
        )


def _team_feature(rows, team: str, suffix: str) -> float:
    if not rows:
        return 0.0
    row = rows[-1]
    prefix = "home" if normalize_key(row.home) == team else "away"
    return float(row.features.get(f"{prefix}_{suffix}_5", 0.0))


def _team_elo(rows, team: str) -> float:
    if not rows:
        return 0.0
    row = rows[-1]
    difference = float(row.features.get("elo_difference", 0.0))
    return difference if normalize_key(row.home) == team else -difference


def _elo_difference(home_rows, away_rows, home: str, away: str) -> float:
    return max(-1.0, min(1.0, _team_elo(home_rows, home) - _team_elo(away_rows, away)))


def _recent_draw_rate(home_rows, away_rows) -> float:
    rows = [*home_rows[-5:], *away_rows[-5:]]
    return sum(row.label == "DRAW" for row in rows) / len(rows) if rows else 0.0


def _recent_goals(home_rows, away_rows) -> float:
    rows = [*home_rows[-5:], *away_rows[-5:]]
    return sum(row.total_goals for row in rows) / len(rows) if rows else 0.0


def _normalise(values: list[float]) -> list[float]:
    total = sum(values)
    return [value / total for value in values]


def _unique(evidence: list[Evidence]) -> list[Evidence]:
    seen = set()
    result = []
    for item in evidence:
        if item.evidence_id not in seen:
            seen.add(item.evidence_id)
            result.append(item)
    return result


def _empty_vector():
    from atlas.vector_memory import VectorMemoryInsight

    return VectorMemoryInsight(
        contexts=[],
        neighbor_count=0,
        confidence=VectorConfidence(
            average_similarity=0.0,
            vector_agreement=0.0,
            coverage=0.0,
            confidence=0.0,
            threshold=0.72,
            reasons=["vector repository not configured"],
        ),
    )
