"""Continuous observation layer — Sprint 3.6.

Watchers observe evolving state on a schedule and feed synthetic
observations through the standard trend pipeline. Atlas detects
tendencies that emerge over time even when no explicit event arrives.
"""

from atlas.watchers.base import (
    Observation,
    ObservationSink,
    Watcher,
    WatcherRegistry,
    WatcherScheduler,
    export_watcher_config,
)
from atlas.watchers.coherencewatcher import CoherenceWatcher
from atlas.watchers.intelligencewatcher import IntelligenceWatcher
from atlas.watchers.janitor import ClusterJanitor
from atlas.watchers.series import InMemorySeriesStore, RedisSeriesStore, Sample, SeriesStore
from atlas.watchers.watchers import (
    LowTrustSignalSource,
    MarketWatcher,
    MatchWatcher,
    NarrativeWatcher,
    NullLowTrustSource,
    RiskWatcher,
)

__all__ = [
    "ClusterJanitor",
    "CoherenceWatcher",
    "InMemorySeriesStore",
    "IntelligenceWatcher",
    "LowTrustSignalSource",
    "MarketWatcher",
    "MatchWatcher",
    "NarrativeWatcher",
    "NullLowTrustSource",
    "Observation",
    "ObservationSink",
    "RedisSeriesStore",
    "RiskWatcher",
    "Sample",
    "SeriesStore",
    "Watcher",
    "WatcherRegistry",
    "WatcherScheduler",
    "export_watcher_config",
]
