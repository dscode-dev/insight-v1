"""ATLAS-VECTOR-B — OracleSimilarityDetector gates + evidence (no DB)."""

from __future__ import annotations

from uuid import uuid4

from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityFilters,
    SimilarityMatch,
    SimilaritySearchResult,
)
from atlas.trends.models import TrendInputs, TrendType
from atlas.trends.oracle_similarity import OracleSimilarityDetector

EV = "atlas-memory-embedding-v1"


def _match(match_id: str, similarity: float, *, competition: str | None = "Serie A") -> SimilarityMatch:
    return SimilarityMatch(
        vector_id=uuid4(),
        match_id=match_id,
        similarity=similarity,
        distance=round(1 - similarity, 6),
        embedding_version=EV,
        feature_schema_version="feature_schema_v2",
        competition=competition,
        season="2024",
    )


def _result(
    matches: list[SimilarityMatch],
    *,
    minimum_similarity: float = 0.72,
    minimum_neighbors: int = 3,
    neighbor_agreement: float = 0.8,
    filters: SimilarityFilters | None = None,
) -> SimilaritySearchResult:
    sims = [m.similarity for m in matches] or [0.0]
    return SimilaritySearchResult(
        matches=matches,
        confidence=SimilarityConfidence(
            similarity_score=round(sum(sims) / len(sims), 6),
            confidence=0.8,
            neighbor_count=len(matches),
            minimum_neighbors=minimum_neighbors,
            average_distance=0.2,
            distance_spread=0.05,
            neighbor_agreement=neighbor_agreement,
            reasons=[],
        ),
        filters=filters
        or SimilarityFilters(
            embedding_version=EV,
            feature_schema_version="feature_schema_v2",
            competition="Serie A",
            season="2024",
        ),
        top_k=25,
        minimum_similarity=minimum_similarity,
    )


def _inputs(result: SimilaritySearchResult | None) -> TrendInputs:
    return TrendInputs(canonical_match_id=uuid4(), similarity=result)


def test_emits_historical_similarity_when_all_gates_pass() -> None:
    matches = [_match(f"m{i}", 0.9 - 0.01 * i) for i in range(4)]
    trends = OracleSimilarityDetector().detect(_inputs(_result(matches)))
    types = {t.trend_type for t in trends}
    assert TrendType.historical_similarity in types
    trend = next(t for t in trends if t.trend_type == TrendType.historical_similarity)
    # Complete evidence (Stage 5).
    ev = trend.evidence
    assert ev["matched_event_ids"] == [m.match_id for m in matches]
    assert ev["embedding_version"] == EV
    assert ev["feature_schema_version"] == "feature_schema_v2"
    assert ev["neighbor_count"] == 4
    assert ev["top_neighbors"] and ev["top_neighbors"][0]["match_id"] == "m0"
    assert "reasoning_summary" in ev and ev["reasoning_summary"]


def test_emits_pattern_only_on_tighter_gate() -> None:
    # 5 neighbours + high agreement → pattern superset condition.
    matches = [_match(f"m{i}", 0.9) for i in range(5)]
    trends = OracleSimilarityDetector().detect(
        _inputs(_result(matches, neighbor_agreement=0.7))
    )
    types = {t.trend_type for t in trends}
    assert TrendType.historical_similarity in types
    assert TrendType.historical_pattern in types


def test_no_pattern_when_neighborhood_is_thin() -> None:
    matches = [_match(f"m{i}", 0.9) for i in range(3)]  # < pattern_min_neighbors
    trends = OracleSimilarityDetector().detect(
        _inputs(_result(matches, neighbor_agreement=0.9))
    )
    types = {t.trend_type for t in trends}
    assert TrendType.historical_similarity in types
    assert TrendType.historical_pattern not in types


def test_emits_nothing_without_similarity() -> None:
    assert OracleSimilarityDetector().detect(_inputs(None)) == []


def test_emits_nothing_below_minimum_neighbors() -> None:
    matches = [_match("m0", 0.9), _match("m1", 0.88)]  # 2 < minimum_neighbors=3
    assert OracleSimilarityDetector().detect(_inputs(_result(matches))) == []


def test_emits_nothing_below_minimum_similarity() -> None:
    matches = [_match(f"m{i}", 0.5) for i in range(4)]  # best 0.5 < 0.72
    assert OracleSimilarityDetector().detect(_inputs(_result(matches))) == []


def test_emits_nothing_on_low_agreement() -> None:
    matches = [_match(f"m{i}", 0.9) for i in range(4)]
    assert (
        OracleSimilarityDetector().detect(
            _inputs(_result(matches, neighbor_agreement=0.1))
        )
        == []
    )


def test_gate_rejects_incompatible_competition() -> None:
    # Query declares Serie A; neighbours are from another competition.
    matches = [_match(f"m{i}", 0.9, competition="Premier League") for i in range(4)]
    assert OracleSimilarityDetector().detect(_inputs(_result(matches))) == []


def test_gate_drops_incompatible_embedding_version_neighbor() -> None:
    # One neighbour on a different embedding version is dropped; the remaining
    # three compatible neighbours still satisfy the gates.
    incompatible = SimilarityMatch(
        vector_id=uuid4(),
        match_id="bad",
        similarity=0.99,
        distance=0.01,
        embedding_version="other-embedding-v9",
        feature_schema_version="feature_schema_v2",
        competition="Serie A",
        season="2024",
    )
    matches = [incompatible] + [_match(f"m{i}", 0.9) for i in range(3)]
    trends = OracleSimilarityDetector().detect(_inputs(_result(matches)))
    assert any(t.trend_type == TrendType.historical_similarity for t in trends)
    ev = next(t.evidence for t in trends)
    assert "bad" not in ev["matched_event_ids"]
