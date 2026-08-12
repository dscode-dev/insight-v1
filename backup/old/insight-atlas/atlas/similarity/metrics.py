"""Similarity observability (Stage 5) — feeds the Insight Console IOC.

Prometheus series covering cache efficiency, pgvector latency, neighbour +
confidence distribution, and rejected / version-incompatible searches.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

SIMILARITY_REQUESTS_TOTAL = Counter(
    "atlas_similarity_requests_total",
    "Similarity context requests by outcome.",
    ["outcome"],  # cache_hit | cache_miss | rejected
)
SIMILARITY_INCOMPATIBLE_TOTAL = Counter(
    "atlas_similarity_incompatible_total",
    "Searches returning no rows while a version/domain filter was declared.",
)
SIMILARITY_QUERY_LATENCY_SECONDS = Histogram(
    "atlas_similarity_query_latency_seconds",
    "pgvector similarity query latency.",
    ["mode"],  # single | batch
)
SIMILARITY_NEIGHBORS = Histogram(
    "atlas_similarity_neighbors",
    "Compatible neighbours returned per search.",
    buckets=(0, 1, 3, 5, 10, 25, 50, 100),
)
SIMILARITY_CONFIDENCE = Histogram(
    "atlas_similarity_confidence",
    "Final similarity confidence distribution.",
    buckets=(0.0, 0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 0.95, 1.0),
)
SIMILARITY_AGREEMENT = Histogram(
    "atlas_similarity_agreement",
    "Neighbour agreement (tightness) distribution.",
    buckets=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
)


def record_context(context, *, cache_hit: bool) -> None:
    """Record one produced SimilarityContext into the metric series."""
    if cache_hit:
        SIMILARITY_REQUESTS_TOTAL.labels(outcome="cache_hit").inc()
        return
    matches = len(context.matches)
    if matches == 0:
        SIMILARITY_REQUESTS_TOTAL.labels(outcome="rejected").inc()
        f = context.filters
        if any(
            v is not None
            for v in (
                f.feature_schema_version,
                f.competition,
                f.season,
                f.market_type,
                f.match_phase,
            )
        ):
            SIMILARITY_INCOMPATIBLE_TOTAL.inc()
    else:
        SIMILARITY_REQUESTS_TOTAL.labels(outcome="cache_miss").inc()
    SIMILARITY_NEIGHBORS.observe(matches)
    SIMILARITY_CONFIDENCE.observe(context.confidence.confidence)
    SIMILARITY_AGREEMENT.observe(context.agreement)


def operational_event(context) -> dict:
    """Structured operational event payload for the IOC stream."""
    return {
        "kind": "atlas.similarity.context",
        "embedding_version": context.embedding_version,
        "feature_schema_version": context.feature_schema_version,
        "neighbor_count": context.confidence.neighbor_count,
        "confidence": context.confidence.confidence,
        "agreement": context.agreement,
        "coverage": context.coverage,
        "reasons": context.reasoning,
    }
