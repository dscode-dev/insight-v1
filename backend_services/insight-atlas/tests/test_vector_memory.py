from __future__ import annotations

from atlas.intelligence.orchestrator import AtlasIntelligenceOrchestrator
from atlas.vector_memory import (
    EMBEDDING_DIMENSIONS,
    DeterministicEmbeddingEncoder,
    DeterministicVectorIndex,
)
from tests.test_intelligence_runtime import _context, _dataset


def _index():
    dataset = _dataset()
    encoder = DeterministicEmbeddingEncoder()
    return dataset, DeterministicVectorIndex(
        [encoder.from_record(record) for record in dataset.records]
    )


def test_embedding_is_deterministic_local_and_fixed_dimension() -> None:
    dataset = _dataset()
    encoder = DeterministicEmbeddingEncoder()
    first = encoder.from_record(dataset.records[0])
    second = encoder.from_record(dataset.records[0])

    assert first == second
    assert len(first.embedding) == EMBEDDING_DIMENSIONS
    assert first.embedding_version == "atlas-memory-embedding-v1"


def test_hybrid_runtime_keeps_vector_memory_last_and_separate() -> None:
    dataset, index = _index()
    report = AtlasIntelligenceOrchestrator(
        dataset, vector_index=index
    ).execute(_context())

    assert report.runtime.engine_order[-2:] == [
        "vector_memory_engine",
        "report_builder",
    ]
    assert report.vector_neighbors == len(report.vector_contexts)
    assert report.vector_neighbors > 0
    assert report.vector_confidence.confidence > 0
    assert report.memory.retrieval_order[0].value == "head_to_head"
    assert report.memory.retrieval_order[-1].value == "generic_similarity"


def test_vector_filters_competition_regime_and_time() -> None:
    dataset, index = _index()
    report = AtlasIntelligenceOrchestrator(
        dataset, vector_index=index
    ).execute(_context())

    assert all(
        item.competition == "brasileirao_serie_a"
        for item in report.vector_contexts
    )
    assert all(
        item.regime.value == report.regime.regime_type.value
        for item in report.vector_contexts
    )
    assert all(item.created_at < report.as_of for item in report.vector_contexts)


def test_vector_memory_can_discover_unrelated_team_contexts_without_replacing_memory() -> None:
    dataset, index = _index()
    report = AtlasIntelligenceOrchestrator(
        dataset, vector_index=index
    ).execute(_context())
    pair = {"santos", "flamengo"}

    assert any(
        not (pair & {item.home_team, item.away_team})
        for item in report.vector_contexts
    )
    assert report.head_to_head.home_team == "santos"
    assert report.head_to_head.away_team == "flamengo"
    assert report.memory.retrieval_order[0].value == "head_to_head"
