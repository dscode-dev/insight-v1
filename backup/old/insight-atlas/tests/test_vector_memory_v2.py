"""Coverage for the ATLAS-SIM-A v2 embedding layout (37 dims) — must
coexist with v1 (32 dims, unchanged) rather than replace it."""

from __future__ import annotations

import pytest

from atlas.intelligence.orchestrator import AtlasIntelligenceOrchestrator
from atlas.strength.models import TeamStrengthFeatures
from atlas.vector_memory import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_DIMENSIONS_V2,
    EMBEDDING_VERSION,
    EMBEDDING_VERSION_V2,
    DeterministicEmbeddingEncoder,
    MemoryEmbeddingV2,
)
from tests.test_intelligence_runtime import _context, _dataset


def _strength() -> TeamStrengthFeatures:
    return TeamStrengthFeatures(
        elo_delta=0.3, home_attack_strength=0.7, away_attack_strength=0.4,
        home_defense_strength=0.6, away_defense_strength=0.5,
        h2h_advantage=0.2, table_position_gap=0.1, rest_advantage=-0.05,
    )


def test_v1_and_v2_dimensions_and_versions_coexist():
    dataset = _dataset()
    encoder = DeterministicEmbeddingEncoder()
    record = dataset.records[0]
    v1 = encoder.from_record(record)
    v2 = encoder.from_record_v2(record)
    assert len(v1.embedding) == EMBEDDING_DIMENSIONS == 32
    assert len(v2.embedding) == EMBEDDING_DIMENSIONS_V2 == 37
    assert v1.embedding_version == EMBEDDING_VERSION == "atlas-memory-embedding-v1"
    assert v2.embedding_version == EMBEDDING_VERSION_V2 == "atlas-memory-embedding-v2"
    assert isinstance(v2, MemoryEmbeddingV2)


def test_from_record_v2_is_deterministic():
    dataset = _dataset()
    encoder = DeterministicEmbeddingEncoder()
    record = dataset.records[0]
    first = encoder.from_record_v2(record)
    second = encoder.from_record_v2(record)
    assert first == second


def test_from_record_v2_is_l2_normalised():
    dataset = _dataset()
    encoder = DeterministicEmbeddingEncoder()
    embedding = encoder.from_record_v2(dataset.records[0])
    norm = sum(v * v for v in embedding.embedding) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_memory_embedding_v2_rejects_wrong_dimension():
    with pytest.raises(ValueError):
        MemoryEmbeddingV2(
            vector_id="00000000-0000-0000-0000-000000000000",
            source_match_id="m1", competition="c", regime="league",
            home_team="a", away_team="b", market_available=False,
            uncertainty=0.5, embedding=tuple([0.0] * 32),  # wrong: v1 length
            created_at="2026-01-01T00:00:00+00:00",
        )


def test_from_report_v2_with_strength_and_market_data():
    dataset = _dataset()
    report = AtlasIntelligenceOrchestrator(dataset).execute(
        _context(), strength_features=_strength()
    )
    encoder = DeterministicEmbeddingEncoder()
    embedding = encoder.from_report_v2(report, strength=_strength(), market=None)
    assert len(embedding.embedding) == EMBEDDING_DIMENSIONS_V2
    assert embedding.embedding_version == EMBEDDING_VERSION_V2


def test_from_report_v2_degrades_gracefully_without_strength_or_market():
    dataset = _dataset()
    report = AtlasIntelligenceOrchestrator(dataset).execute(_context())
    encoder = DeterministicEmbeddingEncoder()
    # No strength/market objects at all -> must not raise, and should
    # fall back to neutral defaults (0.5 elo_delta, matching v1's own
    # from_report placeholder) rather than fabricate specifics.
    embedding = encoder.from_report_v2(report)
    assert len(embedding.embedding) == EMBEDDING_DIMENSIONS_V2
