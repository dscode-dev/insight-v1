"""Named trend engines — Sprint 1.

Each engine is an ISOLATED unit: it owns one detector family, fails
independently (one engine's exception never blinds another), carries
its own metrics label, and stamps its agent name onto every trend it
produces. Engines are independently constructible + testable.

  MarketTrendEngine     (agent "market")     — odds, movement, divergence
  MomentumTrendEngine   (agent "momentum")   — possession/shots/attacks/pressure
  HistoricalTrendEngine (agent "historical") — odds baseline vs history
  ImpactTrendEngine     (agent "impact")     — goals, cards, injuries, lineups
  NarrativeTrendEngine  (agent "narrative")  — sentiment/community features
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from prometheus_client import Counter, Histogram

from atlas.trends.contract import enrich
from atlas.trends.echo import (
    CommunitySignalDetector,
    NarrativeConflictDetector,
    SentimentShiftDetector,
)
from atlas.trends.models import Trend, TrendInputs
from atlas.trends.meta import MetaTrendDetector
from atlas.trends.market_intelligence import (
    MarketConfidenceTrendDetector,
    MarketConsensusTrendDetector,
    MarketDivergenceDetector,
    MarketVolatilityTrendDetector,
    SharpMarketMoveDetector,
)
from atlas.trends.ninja import (
    MarketAccelerationDetector,
    MarketAnomalyDetector,
    MarketDisagreementDetector,
    MarketShiftDetector,
)
from atlas.trends.oracle import HistoricalDeviationDetector
from atlas.trends.oracle_similarity import OracleSimilarityDetector
from atlas.trends.pulse import (
    DominancePatternDetector,
    MomentumShiftDetector,
    PressureBuildingDetector,
    TempoChangeDetector,
)
from atlas.trends.sentinel import (
    GameStateChangeDetector,
    ImpactAssessmentDetector,
    RiskIncreaseDetector,
)

logger = logging.getLogger(__name__)

ENGINE_RUNS_TOTAL = Counter(
    "trend_engine_runs_total",
    "Trend engine executions, by engine and outcome.",
    ["engine", "outcome"],
)
ENGINE_LATENCY_SECONDS = Histogram(
    "trend_engine_latency_seconds",
    "Seconds one trend engine spent over one tick's inputs.",
    ["engine"],
)


class TrendDetector(Protocol):
    def detect(self, inputs: TrendInputs) -> list[Trend]: ...


class BaseTrendEngine:
    """One isolated detector family. `detect` never raises: detector
    failures are logged + counted; the engine returns whatever the
    healthy detectors found, already enriched with Contract V1 fields
    (agent, signals, title, summary)."""

    def __init__(self, name: str, detectors: list[TrendDetector]) -> None:
        self.name = name
        self._detectors = detectors

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        started = time.perf_counter()
        out: list[Trend] = []
        failed = False
        for detector in self._detectors:
            try:
                out.extend(detector.detect(inputs))
            except Exception:  # noqa: BLE001 — detector isolation
                failed = True
                logger.exception(
                    "trend_detector_failed",
                    extra={
                        "engine": self.name,
                        "detector": type(detector).__name__,
                        "canonical_match_id": str(inputs.canonical_match_id),
                    },
                )
        ENGINE_LATENCY_SECONDS.labels(engine=self.name).observe(
            time.perf_counter() - started
        )
        ENGINE_RUNS_TOTAL.labels(
            engine=self.name, outcome="partial_failure" if failed else "ok"
        ).inc()
        return [enrich(t, agent=self.name, signals=inputs.signals) for t in out]


class MarketTrendEngine(BaseTrendEngine):
    """Odds, odds movement, bookmaker divergence → market_shift,
    market_acceleration, market_disagreement, market_anomaly."""

    def __init__(self, detectors: list[TrendDetector] | None = None) -> None:
        super().__init__(
            "market",
            detectors
            if detectors is not None
            else [
                MarketShiftDetector(),
                MarketAccelerationDetector(),
                MarketDisagreementDetector(),
                MarketAnomalyDetector(),
                # Magnus Absorption (Sprint 1) — market_state detectors.
                MarketConsensusTrendDetector(),
                MarketDivergenceDetector(),
                MarketConfidenceTrendDetector(),
                MarketVolatilityTrendDetector(),
                SharpMarketMoveDetector(),
            ],
        )


class MomentumTrendEngine(BaseTrendEngine):
    """Possession, dangerous attacks, shots, pressure indicators →
    momentum_shift, pressure_building, tempo_change, dominance_pattern."""

    def __init__(self, detectors: list[TrendDetector] | None = None) -> None:
        super().__init__(
            "momentum",
            detectors
            if detectors is not None
            else [
                MomentumShiftDetector(),
                PressureBuildingDetector(),
                TempoChangeDetector(),
                DominancePatternDetector(),
            ],
        )


class HistoricalTrendEngine(BaseTrendEngine):
    """Atlas historical data → historical_deviation (odds baseline) +
    historical_similarity / historical_pattern (online pgvector similarity,
    ATLAS-VECTOR-B). OracleSimilarityDetector is a pure consumer of the
    precomputed TrendInputs.similarity result — no DB access in the detector."""

    def __init__(self, detectors: list[TrendDetector] | None = None) -> None:
        super().__init__(
            "historical",
            detectors
            if detectors is not None
            else [
                HistoricalDeviationDetector(),
                OracleSimilarityDetector(),
            ],
        )


class ImpactTrendEngine(BaseTrendEngine):
    """Goals, red cards, injuries, lineup changes → impact_assessment,
    game_state_change, risk_increase."""

    def __init__(self, detectors: list[TrendDetector] | None = None) -> None:
        super().__init__(
            "impact",
            detectors
            if detectors is not None
            else [
                ImpactAssessmentDetector(),
                GameStateChangeDetector(),
                RiskIncreaseDetector(),
            ],
        )


class NarrativeTrendEngine(BaseTrendEngine):
    """Sentiment/community features → narrative_conflict,
    sentiment_shift, community_signal. Numeric features only."""

    def __init__(self, detectors: list[TrendDetector] | None = None) -> None:
        super().__init__(
            "narrative",
            detectors
            if detectors is not None
            else [
                SentimentShiftDetector(),
                NarrativeConflictDetector(),
                CommunitySignalDetector(),
            ],
        )


class MetaTrendEngine(BaseTrendEngine):
    """Recurring cross-match intelligence (Maturity Sprint 1.5) →
    MARKET_UNDERESTIMATION/OVERESTIMATION, RECURRING_VOLATILITY,
    RECURRING_CONFIDENCE_FAILURE, RECURRING_SHARP_REVERSAL."""

    def __init__(self, detectors: list[TrendDetector] | None = None) -> None:
        super().__init__(
            "meta",
            detectors if detectors is not None else [MetaTrendDetector()],
        )


def default_engines() -> list[BaseTrendEngine]:
    """The V1 engine set in deterministic order."""
    return [
        MarketTrendEngine(),
        MomentumTrendEngine(),
        HistoricalTrendEngine(),
        ImpactTrendEngine(),
        NarrativeTrendEngine(),
        MetaTrendEngine(),
    ]
