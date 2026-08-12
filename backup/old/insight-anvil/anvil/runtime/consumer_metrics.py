"""Prometheus instrumentation for the Anvil consumer runtime.

This module exposes counters and histograms that the consumer, handler, and
state store update directly. The registry is the default `prometheus_client`
process registry; the `/metrics` endpoint served by `HealthServer` reads
from the same registry.

Design notes:
  * Labels are kept low-cardinality: `stream`, `group`, `event_type`,
    `decision`, `outcome`. Anything per-`match_id` or per-`user_id` would
    explode the cardinality and is intentionally *not* labelled.
  * Histograms use buckets aligned with realistic real-time workloads:
    sub-millisecond is irrelevant for a Redis-IO-bound consumer, multi-
    second is the alarm range. Adjust later based on SLO.
  * `prometheus_client` is an unconditional dependency; if it's missing
    we want an explicit ImportError rather than a silent no-op so
    operators can't accidentally deploy without metrics.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Histogram,
    generate_latest,
)

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

events_processed_total = Counter(
    "anvil_events_processed_total",
    "Events successfully processed and acknowledged.",
    labelnames=("stream", "group", "event_type", "source"),
)

events_failed_total = Counter(
    "anvil_events_failed_total",
    "Events that raised during handler execution (any retry budget).",
    labelnames=("stream", "group", "event_type", "source"),
)

events_dlq_total = Counter(
    "anvil_events_dlq_total",
    "Events that exhausted retries and were pushed to DLQ.",
    labelnames=("stream", "group", "outcome"),  # outcome=ok|dlq_unreachable
)

derived_published_total = Counter(
    "anvil_derived_published_total",
    "Derived events published downstream.",
    labelnames=("event_type",),
)

derived_publish_skipped_total = Counter(
    "anvil_derived_publish_skipped_total",
    "Derived publishes skipped by the idempotency claim.",
    labelnames=("event_type",),
)

state_cas_conflicts_total = Counter(
    "anvil_state_cas_conflicts_total",
    "MatchState CAS rejections (caller will retry).",
)

state_schema_mismatch_total = Counter(
    "anvil_state_schema_mismatch_total",
    "MatchState loads that hit a schema_version mismatch and were treated as absent.",
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

_LATENCY_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)

handler_duration_seconds = Histogram(
    "anvil_handler_duration_seconds",
    "Wall-clock duration of consumer handler execution.",
    labelnames=("stream", "event_type"),
    buckets=_LATENCY_BUCKETS,
)

event_end_to_end_lag_seconds = Histogram(
    "anvil_event_end_to_end_lag_seconds",
    "Wall-clock lag between event ts_ingest and ACK.",
    labelnames=("stream", "event_type"),
    buckets=(
        0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0,
    ),
)


def render_metrics() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
