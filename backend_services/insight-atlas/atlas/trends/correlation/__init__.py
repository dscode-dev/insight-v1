"""Trend Correlation Engine — Sprint 1.5 Part 2."""

from atlas.trends.correlation.engine import TrendCorrelationEngine
from atlas.trends.correlation.models import (
    DEFAULT_CORRELATION_RULES,
    CorrelatedTrend,
    CorrelationRule,
    CorrelationType,
)
from atlas.trends.correlation.repository import CorrelatedTrendRepository
from atlas.trends.correlation.store import (
    InMemoryRecentTrendStore,
    RedisRecentTrendStore,
    TrendSighting,
)

__all__ = [
    "DEFAULT_CORRELATION_RULES",
    "CorrelatedTrend",
    "CorrelatedTrendRepository",
    "CorrelationRule",
    "CorrelationType",
    "InMemoryRecentTrendStore",
    "RedisRecentTrendStore",
    "TrendCorrelationEngine",
    "TrendSighting",
]
