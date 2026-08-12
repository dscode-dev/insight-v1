"""Event Aggregation — Sprint 6.2 Part 6.

Many medium events together can be meaningful (3 yellow cards in 10
minutes → an aggressive match; sustained pressure for 15 minutes → a
pressure spike). This module accumulates events in configurable
windows and emits aggregated Signals once a threshold is crossed.
Redis-backed in production; in-memory for tests / single instance.
"""

from atlas.event_aggregation.engine import (
    DEFAULT_AGGREGATION_POLICIES,
    AggregationEngine,
    AggregationPolicy,
)
from atlas.event_aggregation.store import (
    AggregationStore,
    InMemoryAggregationStore,
    RedisAggregationStore,
)

__all__ = [
    "DEFAULT_AGGREGATION_POLICIES",
    "AggregationEngine",
    "AggregationPolicy",
    "AggregationStore",
    "InMemoryAggregationStore",
    "RedisAggregationStore",
]
