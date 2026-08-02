"""ATLAS-SIMILARITY-A — SimilarityService cache + batch + context (no DB)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from atlas.similarity.cache import SimilarityCache, cache_key
from atlas.similarity.contracts import (
    SimilarityContext,
    SimilarityFilters,
    SimilarityMatch,
    SimilaritySearchRequest,
)
from atlas.similarity.service import SimilarityService
from atlas.vector_memory.contracts import EMBEDDING_DIMENSIONS, EMBEDDING_VERSION

VEC = tuple([1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1))


def _match(match_id: str, similarity: float) -> SimilarityMatch:
    return SimilarityMatch(
        vector_id=uuid4(),
        match_id=match_id,
        similarity=similarity,
        distance=round(1 - similarity, 6),
        embedding_version=EMBEDDING_VERSION,
        feature_schema_version="feature_schema_v2",
    )


class _FakeRepo:
    def __init__(self, matches: list[SimilarityMatch]) -> None:
        self._matches = matches
        self.search_calls = 0
        self.batch_calls = 0

    async def search_matches(self, request: SimilaritySearchRequest) -> list[SimilarityMatch]:
        self.search_calls += 1
        return list(self._matches)

    async def batch_search_matches(self, requests) -> list[list[SimilarityMatch]]:
        self.batch_calls += 1
        return [list(self._matches) for _ in requests]


def _request() -> SimilaritySearchRequest:
    return SimilaritySearchRequest(
        embedding=VEC,
        filters=SimilarityFilters(embedding_version=EMBEDDING_VERSION),
        top_k=25,
        minimum_similarity=0.5,
        minimum_neighbors=3,
    )


@pytest.mark.asyncio
async def test_context_is_superset_and_computes_facets() -> None:
    repo = _FakeRepo([_match("a", 0.9), _match("b", 0.8), _match("c", 0.7)])
    ctx = await SimilarityService(repo, cache=SimilarityCache()).context(_request())
    # SimilaritySearchResult-compatible surface (Oracle reads these):
    assert ctx.matches and ctx.confidence and ctx.filters
    assert ctx.minimum_similarity == 0.5
    # First-class facets:
    assert 0.0 <= ctx.agreement <= 1.0
    assert ctx.coverage == 1.0  # 3 matches / minimum_neighbors 3
    assert ctx.distribution.count == 3
    assert ctx.embedding_version == EMBEDDING_VERSION
    assert isinstance(ctx.reasoning, list)


@pytest.mark.asyncio
async def test_cache_is_transparent_and_avoids_second_query() -> None:
    repo = _FakeRepo([_match("a", 0.9)])
    service = SimilarityService(repo, cache=SimilarityCache(ttl_seconds=60))
    first = await service.context(_request(), canonical_match_id="m1")
    second = await service.context(_request(), canonical_match_id="m1")
    assert repo.search_calls == 1  # second served from cache
    assert first.matches[0].match_id == second.matches[0].match_id


@pytest.mark.asyncio
async def test_version_change_never_returns_stale_cache() -> None:
    repo = _FakeRepo([_match("a", 0.9)])
    service = SimilarityService(repo, cache=SimilarityCache(ttl_seconds=60))
    await service.context(_request(), canonical_match_id="m1")
    bumped = SimilaritySearchRequest(
        embedding=VEC,
        filters=SimilarityFilters(
            embedding_version=EMBEDDING_VERSION,
            feature_schema_version="feature_schema_v3",  # version bump
        ),
        top_k=25,
        minimum_similarity=0.5,
        minimum_neighbors=3,
    )
    await service.context(bumped, canonical_match_id="m1")
    assert repo.search_calls == 2  # different key → not stale


@pytest.mark.asyncio
async def test_batch_context_preserves_order_and_uses_batch_query() -> None:
    repo = _FakeRepo([_match("a", 0.9)])
    service = SimilarityService(repo, cache=SimilarityCache(ttl_seconds=0))  # no cache
    requests = [_request() for _ in range(3)]
    ids = ["m0", "m1", "m2"]
    contexts = await service.batch_context(requests, canonical_match_ids=ids)
    assert len(contexts) == 3
    assert repo.batch_calls == 1  # single batched call
    assert repo.search_calls == 0


def test_cache_key_folds_versions_and_domain() -> None:
    k1 = cache_key(_request(), canonical_match_id="m1")
    other = SimilaritySearchRequest(
        embedding=VEC,
        filters=SimilarityFilters(
            embedding_version=EMBEDDING_VERSION, competition="Serie A"
        ),
        top_k=25,
        minimum_similarity=0.5,
        minimum_neighbors=3,
    )
    assert k1 != cache_key(other, canonical_match_id="m1")


def test_cache_ttl_zero_disables_storage() -> None:
    cache = SimilarityCache(ttl_seconds=0)
    ctx = SimilarityContext(
        matches=[], confidence=_request_confidence(), filters=SimilarityFilters(),
        top_k=1, minimum_similarity=0.5, agreement=0.0, coverage=0.0,
        distribution=_empty_dist(), embedding_version=EMBEDDING_VERSION,
    )
    cache.put("k", ctx)
    assert cache.get("k") is None


def _request_confidence():
    from atlas.similarity.contracts import SimilarityConfidence

    return SimilarityConfidence(
        similarity_score=0.0, confidence=0.0, neighbor_count=0, minimum_neighbors=3,
        average_distance=0.0, distance_spread=0.0, neighbor_agreement=0.0,
    )


def _empty_dist():
    from atlas.similarity.contracts import SimilarityDistribution

    return SimilarityDistribution(
        count=0, best_similarity=0.0, worst_similarity=0.0, mean_similarity=0.0,
        min_distance=0.0, max_distance=0.0, mean_distance=0.0, distance_spread=0.0,
    )
