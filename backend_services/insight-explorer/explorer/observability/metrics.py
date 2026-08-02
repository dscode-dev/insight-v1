"""Prometheus metrics (Step 10).

Names are frozen by ML_A_OBSERVABILITY and the ML-B spec. Importing this
module is side-effect-free except for registering collectors against a
private registry so repeated imports in tests don't raise duplicate-series.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

# --- Job + volume metrics ------------------------------------------------

jobs_total = Counter(
    "explorer_jobs_total", "Explorer jobs run.", ["competition", "source", "status"],
    registry=REGISTRY,
)
job_duration_seconds = Histogram(
    "explorer_job_duration_seconds", "Job wall-clock duration.", ["competition", "source"],
    registry=REGISTRY,
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200),
)
records_collected_total = Counter(
    "explorer_records_collected_total", "Raw records collected.",
    ["competition", "source", "entity_type"], registry=REGISTRY,
)
records_normalized_total = Counter(
    "explorer_records_normalized_total", "Records normalized to envelope.",
    ["competition", "source", "entity_type"], registry=REGISTRY,
)
records_validated_total = Counter(
    "explorer_records_validated_total", "Records that passed validation.",
    ["competition", "source", "entity_type"], registry=REGISTRY,
)
records_rejected_total = Counter(
    "explorer_records_rejected_total", "Records rejected.",
    ["competition", "source", "entity_type", "reason"], registry=REGISTRY,
)
sources_online = Gauge(
    "explorer_sources_online", "Sources currently reachable.", ["source"], registry=REGISTRY,
)
sources_failed = Counter(
    "explorer_sources_failed_total", "Source failure events.", ["source"], registry=REGISTRY,
)
dataset_size_bytes = Gauge(
    "explorer_dataset_size_bytes", "Data lake size by layer.", ["layer"], registry=REGISTRY,
)
validation_errors_total = Counter(
    "explorer_validation_errors_total", "Validation rule violations.",
    ["competition", "source", "rule"], registry=REGISTRY,
)

# --- AI metrics ----------------------------------------------------------

ai_requests_total = Counter(
    "explorer_ai_requests_total", "AI (Qwen) requests.", ["agent", "status"], registry=REGISTRY,
)
ai_tokens_total = Counter(
    "explorer_ai_tokens_total", "AI tokens consumed.", ["agent", "kind"], registry=REGISTRY,
)
ai_failures_total = Counter(
    "explorer_ai_failures_total", "AI runtime failures.", ["agent", "reason"], registry=REGISTRY,
)
ai_latency_seconds = Histogram(
    "explorer_ai_latency_seconds", "AI request latency.", ["agent"], registry=REGISTRY,
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)


def render() -> bytes:
    """Prometheus exposition text for the /explorer/metrics endpoint."""
    return generate_latest(REGISTRY)
