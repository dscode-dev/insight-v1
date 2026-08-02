"""Anvil-specific Prometheus metrics.

Complements the consumer counters in consumer_metrics.py (so
operator dashboards stay cross-service-comparable) and adds analytics-specific
ones for batch behaviour and ClickHouse health.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# Per-event-type ingest counter. Same shape regardless of destination table.
derived_events_persisted_total = Counter(
    "anvil_derived_events_persisted_total",
    "Derived events written to ClickHouse, by event type.",
    labelnames=("event_type",),
)

derived_events_skipped_total = Counter(
    "anvil_derived_events_skipped_total",
    "Derived events the handler intentionally skipped (unsupported type, etc).",
    labelnames=("reason",),
)

batch_flushes_total = Counter(
    "anvil_batch_flushes_total",
    "Number of batch flushes the inserter performed.",
    labelnames=("table", "reason"),
)

batch_rows_total = Counter(
    "anvil_batch_rows_total",
    "Total rows inserted into ClickHouse.",
    labelnames=("table",),
)

batch_flush_failures_total = Counter(
    "anvil_batch_flush_failures_total",
    "Insert failures that re-queued rows to the buffer.",
    labelnames=("table",),
)

# Histogram so dashboards can graph p99 of CH insert latency.
batch_flush_duration_seconds = Histogram(
    "anvil_batch_flush_duration_seconds",
    "Wall-clock time to flush a batch (per-table).",
    labelnames=("table",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
