"""In-memory validation index matching pgvector cosine semantics."""

from __future__ import annotations

from atlas.vector_memory.contracts import (
    MemoryEmbedding,
    VectorConfidence,
    VectorMemoryInsight,
    VectorNeighbor,
)
from atlas.vector_memory.embedding import cosine_similarity


class DeterministicVectorIndex:
    def __init__(self, embeddings: list[MemoryEmbedding]) -> None:
        self._embeddings = tuple(embeddings)

    def search(
        self,
        query: MemoryEmbedding,
        *,
        threshold: float = 0.72,
        limit: int = 25,
    ) -> VectorMemoryInsight:
        candidates = []
        for candidate in self._embeddings:
            if candidate.source_match_id == query.source_match_id:
                continue
            if candidate.created_at >= query.created_at:
                continue
            if candidate.competition != query.competition:
                continue
            if candidate.regime != query.regime:
                continue
            similarity = cosine_similarity(query.embedding, candidate.embedding)
            if similarity < threshold:
                continue
            candidates.append((similarity, candidate))
        candidates.sort(
            key=lambda item: (-item[0], item[1].created_at, item[1].source_match_id)
        )
        return vector_insight(query, candidates[:limit], threshold=threshold)


def vector_insight(
    query: MemoryEmbedding,
    candidates: list[tuple[float, MemoryEmbedding]],
    *,
    threshold: float,
) -> VectorMemoryInsight:
    neighbors = []
    agreements = []
    query_behavior = set(query.behavior)
    query_trends = set(query.trends)
    query_signals = set(query.signals)
    for similarity, candidate in candidates:
        shared_behavior = sorted(query_behavior.intersection(candidate.behavior))
        shared_trends = sorted(query_trends.intersection(candidate.trends))
        shared_signals = sorted(query_signals.intersection(candidate.signals))
        denominator = max(
            1,
            len(query_behavior) + len(query_trends) + len(query_signals),
        )
        agreements.append(
            (
                len(shared_behavior)
                + len(shared_trends)
                + len(shared_signals)
            )
            / denominator
        )
        neighbors.append(
            VectorNeighbor(
                vector_id=candidate.vector_id,
                source_match_id=candidate.source_match_id,
                competition=candidate.competition,
                regime=candidate.regime,
                home_team=candidate.home_team,
                away_team=candidate.away_team,
                similarity=round(similarity, 6),
                shared_behaviors=shared_behavior,
                shared_trends=shared_trends,
                shared_signals=shared_signals,
                created_at=candidate.created_at,
            )
        )
    average = (
        sum(item.similarity for item in neighbors) / len(neighbors)
        if neighbors
        else 0.0
    )
    agreement = sum(agreements) / len(agreements) if agreements else 0.0
    coverage = min(1.0, len(neighbors) / 10)
    confidence = min(0.95, average * (0.55 + 0.25 * agreement + 0.20 * coverage))
    reasons = []
    if not neighbors:
        reasons.append("no vector neighbors met metadata and distance thresholds")
    if neighbors and agreement < 0.4:
        reasons.append("vector neighbors have limited semantic agreement")
    if len(neighbors) < 5:
        reasons.append("thin vector neighborhood")
    return VectorMemoryInsight(
        contexts=neighbors,
        neighbor_count=len(neighbors),
        confidence=VectorConfidence(
            average_similarity=round(average, 6),
            vector_agreement=round(agreement, 6),
            coverage=round(coverage, 6),
            confidence=round(confidence, 6),
            threshold=threshold,
            reasons=reasons,
        ),
    )

