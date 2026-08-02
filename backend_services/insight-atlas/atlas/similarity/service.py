"""SimilarityService — the reusable orchestration layer (Stage 4).

Cache lookup → storage lookup → deterministic scoring → SimilarityContext, with
metrics + structured events. Consumer-neutral: Oracle, Behavior, Reasoning,
Atlas Intelligence and Memory can all depend on this single service. The
repository is storage-only; ALL business logic lives here.
"""

from __future__ import annotations

import logging
import time

from atlas.similarity.cache import SimilarityCache, cache_key
from atlas.similarity.capability import (
    SimilarityCapabilities,
    SimilarityDomain,
    SimilarityHealth,
)
from atlas.similarity.contracts import (
    SimilarityContext,
    SimilarityMatch,
    SimilaritySearchRequest,
)
from atlas.similarity.metrics import (
    SIMILARITY_QUERY_LATENCY_SECONDS,
    record_context,
)
from atlas.similarity.repository import SimilarityRepository
from atlas.similarity.scoring import (
    confidence_for_matches,
    coverage_for_matches,
    distribution_for_matches,
)

logger = logging.getLogger("atlas.similarity")


def _event(stage: str, *, consumer: str, **fields: object) -> None:
    """Shared, consumer-tagged similarity lifecycle event (feeds the IOC)."""
    logger.info(
        "similarity_%s", stage, extra={"stage": stage, "consumer": consumer, **fields}
    )


class SimilarityService:
    def __init__(
        self,
        repository: SimilarityRepository,
        *,
        cache: SimilarityCache | None = None,
    ) -> None:
        self._repo = repository
        self._cache = cache if cache is not None else SimilarityCache()

    async def context(
        self,
        request: SimilaritySearchRequest,
        *,
        canonical_match_id: str | None = None,
        consumer: str = "unknown",
    ) -> SimilarityContext:
        """Cache-transparent single search → SimilarityContext.

        The ONE canonical online-vector entry point. Every consumer (Oracle,
        Intelligence Workspace, Memory, …) passes a `consumer` tag for shared,
        consumer-neutral observability — no consumer-specific telemetry.
        """
        _event("request_started", consumer=consumer, top_k=request.top_k)
        key = cache_key(request, canonical_match_id=canonical_match_id)
        cached = self._cache.get(key)
        if cached is not None:
            record_context(cached, cache_hit=True)
            _event(
                "cache_hit",
                consumer=consumer,
                neighbor_count=cached.confidence.neighbor_count,
                confidence=cached.confidence.confidence,
            )
            return cached

        _event("cache_miss", consumer=consumer)
        started = time.perf_counter()
        _event("repository_query", consumer=consumer)
        matches = await self._repo.search_matches(request)
        latency = time.perf_counter() - started
        SIMILARITY_QUERY_LATENCY_SECONDS.labels(mode="single").observe(latency)
        context = self._build_context(request, matches)
        self._cache.put(key, context)
        record_context(context, cache_hit=False)
        _event(
            "query_completed",
            consumer=consumer,
            latency_ms=round(latency * 1000, 3),
            neighbor_count=context.confidence.neighbor_count,
            confidence=context.confidence.confidence,
        )
        _event("context_created", consumer=consumer)
        return context

    async def batch_context(
        self,
        requests: list[SimilaritySearchRequest],
        *,
        canonical_match_ids: list[str | None] | None = None,
        consumer: str = "unknown",
    ) -> list[SimilarityContext]:
        """Batch search preserving 1:1 order. Cache hits are served locally; the
        remaining misses go through the true single-session batch query."""
        if not requests:
            return []
        ids = canonical_match_ids or [None] * len(requests)
        keys = [cache_key(r, canonical_match_id=i) for r, i in zip(requests, ids, strict=True)]
        results: list[SimilarityContext | None] = [self._cache.get(k) for k in keys]
        for ctx in results:
            if ctx is not None:
                record_context(ctx, cache_hit=True)

        miss_index = [i for i, ctx in enumerate(results) if ctx is None]
        if miss_index:
            started = time.perf_counter()
            batched = await self._repo.batch_search_matches(
                [requests[i] for i in miss_index]
            )
            batch_latency = time.perf_counter() - started
            SIMILARITY_QUERY_LATENCY_SECONDS.labels(mode="batch").observe(batch_latency)
            _event(
                "query_completed",
                consumer=consumer,
                latency_ms=round(batch_latency * 1000, 3),
                neighbor_count=len(miss_index),
            )
            for slot, matches in zip(miss_index, batched, strict=True):
                context = self._build_context(requests[slot], matches)
                self._cache.put(keys[slot], context)
                record_context(context, cache_hit=False)
                results[slot] = context
        return [ctx for ctx in results if ctx is not None]

    # -- SimilarityCapability conformance (ATLAS-SIMILARITY-C) -----------------
    # Additive, behaviour-free: `batch` aliases `batch_context`; `health` and
    # `capabilities` are side-effect-free descriptors.

    async def batch(
        self,
        requests: list[SimilaritySearchRequest],
        *,
        canonical_match_ids: list[str | None] | None = None,
        consumer: str = "unknown",
    ) -> list[SimilarityContext]:
        return await self.batch_context(
            requests, canonical_match_ids=canonical_match_ids, consumer=consumer
        )

    def health(self) -> SimilarityHealth:
        return SimilarityHealth(
            domain=SimilarityDomain.online,
            healthy=self._repo is not None,
            detail="online pgvector similarity service",
        )

    def capabilities(self) -> SimilarityCapabilities:
        return SimilarityCapabilities(
            domain=SimilarityDomain.online,
            backend="pgvector",
            supports_cache=True,
            supports_batch=True,
            supports_version_filters=True,
        )

    # -- context assembly (business logic — was in the repository) ------------

    def _build_context(
        self,
        request: SimilaritySearchRequest,
        matches: list[SimilarityMatch],
    ) -> SimilarityContext:
        confidence = confidence_for_matches(
            matches, minimum_neighbors=request.minimum_neighbors
        )
        coverage = coverage_for_matches(
            matches, minimum_neighbors=request.minimum_neighbors
        )
        distribution = distribution_for_matches(matches)
        f = request.filters
        reasoning = list(confidence.reasons)
        if not matches:
            reasoning.append("no compatible neighbours")
        return SimilarityContext(
            matches=matches,
            confidence=confidence,
            filters=f,
            top_k=request.top_k,
            minimum_similarity=request.minimum_similarity,
            agreement=confidence.neighbor_agreement,
            coverage=coverage,
            distribution=distribution,
            reasoning=reasoning,
            metadata={
                "minimum_neighbors": request.minimum_neighbors,
                "requested_top_k": request.top_k,
            },
            embedding_version=f.embedding_version,
            feature_schema_version=f.feature_schema_version,
            signal_catalog_version=f.signal_catalog_version,
            behavior_catalog_version=f.behavior_catalog_version,
        )


# ATLAS-SIMILARITY-C — naming evolution. The online realtime provider's intended
# name is OnlineSimilarityService; `SimilarityService` is kept as the canonical,
# non-breaking alias so existing imports (app.py, deps.py, tests) keep working.
OnlineSimilarityService = SimilarityService
