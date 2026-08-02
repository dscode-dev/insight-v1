"""Trend Intelligence Engine — Sprint 0 foundation.

Atlas's primary output layer: correlates signals, contexts, odds and
features into typed Trends across five detector families (ninja /
pulse / oracle / sentinel / echo), persists them, and publishes
structured trend events onto the trend stream for downstream services.

Atlas never generates posts, never calls LLMs, never knows about users.
"""

from atlas.trends.engine import TrendEngine, default_detectors
from atlas.trends.engines import (
    BaseTrendEngine,
    HistoricalTrendEngine,
    ImpactTrendEngine,
    MarketTrendEngine,
    MomentumTrendEngine,
    NarrativeTrendEngine,
    TrendDetector,
    default_engines,
)
from atlas.trends.models import (
    CATEGORY_OF,
    TREND_SCHEMA_VERSION,
    Severity,
    Trend,
    TrendCategory,
    TrendInputs,
    TrendType,
    severity_for,
)
from atlas.trends.correlation import (
    CorrelatedTrend,
    CorrelatedTrendRepository,
    CorrelationType,
    TrendCorrelationEngine,
)
from atlas.trends.lifecycle import (
    TrendInstance,
    TrendLifecycleEngine,
    TrendLifecycleRepository,
    TrendLifecycleState,
)
from atlas.trends.pipeline import TrendIntelligencePipeline, TrendPipelineResult
from atlas.trends.publisher import TrendPublisher
from atlas.trends.repository import TrendRepository
from atlas.trends.scoring import (
    PublicationTier,
    PublishScore,
    PublishScoreEngine,
    tier_for,
)

__all__ = [
    "CorrelatedTrend",
    "CorrelatedTrendRepository",
    "CorrelationType",
    "PublicationTier",
    "PublishScore",
    "PublishScoreEngine",
    "TrendCorrelationEngine",
    "TrendInstance",
    "TrendIntelligencePipeline",
    "TrendLifecycleEngine",
    "TrendLifecycleRepository",
    "TrendLifecycleState",
    "TrendPipelineResult",
    "tier_for",
    "CATEGORY_OF",
    "TREND_SCHEMA_VERSION",
    "BaseTrendEngine",
    "HistoricalTrendEngine",
    "ImpactTrendEngine",
    "MarketTrendEngine",
    "MomentumTrendEngine",
    "NarrativeTrendEngine",
    "Severity",
    "Trend",
    "TrendCategory",
    "TrendDetector",
    "TrendEngine",
    "TrendInputs",
    "TrendPublisher",
    "TrendRepository",
    "TrendType",
    "default_detectors",
    "default_engines",
    "severity_for",
]
