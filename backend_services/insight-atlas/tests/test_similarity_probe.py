"""ATLAS-VECTOR-B — OnlineSimilarityProbe embed + query seam (no DB)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityContext,
    SimilarityDistribution,
    SimilaritySearchRequest,
)
from atlas.trends.models import TrendInputs
from atlas.trends.similarity_probe import OnlineSimilarityProbe, embed_trend_inputs
from atlas.vector_memory.contracts import EMBEDDING_DIMENSIONS, EMBEDDING_VERSION


class _FakeService:
    def __init__(self) -> None:
        self.last_request: SimilaritySearchRequest | None = None
        self.last_match_id: str | None = None

    async def context(
        self,
        request: SimilaritySearchRequest,
        *,
        canonical_match_id: str | None = None,
        consumer: str = "unknown",
    ) -> SimilarityContext:
        self.last_request = request
        self.last_match_id = canonical_match_id
        self.last_consumer = consumer
        return SimilarityContext(
            matches=[],
            confidence=SimilarityConfidence(
                similarity_score=0.0,
                confidence=0.0,
                neighbor_count=0,
                minimum_neighbors=request.minimum_neighbors,
                average_distance=0.0,
                distance_spread=0.0,
                neighbor_agreement=0.0,
            ),
            filters=request.filters,
            top_k=request.top_k,
            minimum_similarity=request.minimum_similarity,
            agreement=0.0,
            coverage=0.0,
            distribution=SimilarityDistribution(
                count=0, best_similarity=0.0, worst_similarity=0.0,
                mean_similarity=0.0, min_distance=0.0, max_distance=0.0,
                mean_distance=0.0, distance_spread=0.0,
            ),
            embedding_version=request.filters.embedding_version,
        )


def test_embed_returns_none_when_tick_has_no_signal() -> None:
    assert embed_trend_inputs(TrendInputs(canonical_match_id=uuid4())) is None


def test_embed_builds_normalised_32d_vector() -> None:
    inputs = TrendInputs(
        canonical_match_id=uuid4(),
        context={"momentum": 0.6, "pressure": 0.4},
        features={"signal_density": 0.5, "volatility": 0.3},
    )
    vector = embed_trend_inputs(inputs)
    assert vector is not None
    assert len(vector) == EMBEDDING_DIMENSIONS
    norm = sum(v * v for v in vector) ** 0.5
    assert 0.99 <= norm <= 1.01  # unit-normalised


@pytest.mark.asyncio
async def test_probe_queries_service_with_version_filters() -> None:
    service = _FakeService()
    match_id = uuid4()
    inputs = TrendInputs(
        canonical_match_id=match_id,
        features={"momentum_score": 0.7, "signal_density": 0.5, "volatility": 0.2},
    )
    result = await OnlineSimilarityProbe(service).probe(inputs)
    assert result is not None
    assert service.last_request is not None
    assert service.last_request.filters.embedding_version == EMBEDDING_VERSION
    assert service.last_request.filters.feature_schema_version is not None
    assert service.last_match_id == str(match_id)
    assert service.last_consumer == "oracle"  # ATLAS-SIMILARITY-B consumer tag


@pytest.mark.asyncio
async def test_probe_returns_none_without_signal() -> None:
    service = _FakeService()
    result = await OnlineSimilarityProbe(service).probe(
        TrendInputs(canonical_match_id=uuid4())
    )
    assert result is None
    assert service.last_request is None
