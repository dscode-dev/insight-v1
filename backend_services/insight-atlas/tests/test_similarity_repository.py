from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atlas.similarity import (
    SimilarityFilters,
    SimilarityMatch,
    SimilaritySearchRequest,
    TimeWindow,
)
from atlas.similarity.repository import confidence_for_matches
from atlas.vector_memory.contracts import EMBEDDING_DIMENSIONS, EMBEDDING_VERSION


def _match(similarity: float, distance: float) -> SimilarityMatch:
    return SimilarityMatch(
        vector_id=uuid4(),
        match_id=str(uuid4()),
        similarity=similarity,
        distance=distance,
        embedding_version=EMBEDDING_VERSION,
        metadata={"behavior": ["stable"]},
        explanation=["test"],
    )


def test_similarity_request_requires_fixed_embedding_dimension() -> None:
    with pytest.raises(ValidationError):
        SimilaritySearchRequest(embedding=(0.0,) * (EMBEDDING_DIMENSIONS - 1))


def test_similarity_filters_require_embedding_version() -> None:
    with pytest.raises(ValidationError):
        SimilarityFilters(embedding_version="")


def test_similarity_filters_support_version_and_domain_metadata() -> None:
    filters = SimilarityFilters(
        embedding_version=EMBEDDING_VERSION,
        feature_schema_version="feature_schema_v3",
        signal_catalog_version="signal_catalog_v1",
        behavior_catalog_version="behavior_catalog_v1",
        competition="Premier League",
        season="2024",
        market_type="pre_match",
        match_phase="full_time",
        time_window=TimeWindow(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 1, tzinfo=UTC),
        ),
    )

    assert filters.embedding_version == EMBEDDING_VERSION
    assert filters.feature_schema_version == "feature_schema_v3"
    assert filters.competition == "Premier League"
    assert filters.time_window is not None


def test_similarity_confidence_is_deterministic_and_penalizes_thin_neighborhood() -> None:
    thin = confidence_for_matches([_match(0.9, 0.1)], minimum_neighbors=3)
    dense = confidence_for_matches(
        [_match(0.9, 0.1), _match(0.88, 0.12), _match(0.86, 0.14)],
        minimum_neighbors=3,
    )

    assert thin.neighbor_count == 1
    assert "fewer neighbors than minimum_neighbors" in thin.reasons
    assert dense.neighbor_count == 3
    assert dense.confidence > thin.confidence
    assert dense.similarity_score == pytest.approx(0.892, abs=0.001)


def test_similarity_confidence_handles_no_matches() -> None:
    confidence = confidence_for_matches([], minimum_neighbors=3)

    assert confidence.confidence == 0
    assert confidence.neighbor_count == 0
    assert confidence.reasons == [
        "no vector neighbors met filters and similarity threshold"
    ]
