"""Deterministic similarity scoring (ATLAS-SIMILARITY-A).

Business logic that used to live inside the repository. The repository is now
storage-only; the SimilarityService composes these pure functions into a
SimilarityContext. Behaviour is byte-for-byte identical to the ATLAS-VECTOR-B
`confidence_for_matches` — no threshold recalibration.
"""

from __future__ import annotations

from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityDistribution,
    SimilarityMatch,
)


def confidence_for_matches(
    matches: list[SimilarityMatch],
    *,
    minimum_neighbors: int,
) -> SimilarityConfidence:
    if not matches:
        return SimilarityConfidence(
            similarity_score=0.0,
            confidence=0.0,
            neighbor_count=0,
            minimum_neighbors=minimum_neighbors,
            average_distance=0.0,
            distance_spread=0.0,
            neighbor_agreement=0.0,
            reasons=["no vector neighbors met filters and similarity threshold"],
        )

    similarities = [item.similarity for item in matches]
    distances = [item.distance for item in matches]
    best_similarity = max(similarities)
    average_similarity = sum(similarities) / len(similarities)
    similarity_score = (0.6 * best_similarity) + (0.4 * average_similarity)

    average_distance = sum(distances) / len(distances)
    distance_spread = max(distances) - min(distances)
    neighbor_agreement = 1.0 - min(
        1.0,
        distance_spread / max(average_distance, 1e-9),
    )
    coverage = min(1.0, len(matches) / minimum_neighbors)
    confidence = min(
        0.99,
        similarity_score * (0.50 + 0.25 * neighbor_agreement + 0.25 * coverage),
    )
    reasons = []
    if len(matches) < minimum_neighbors:
        reasons.append("fewer neighbors than minimum_neighbors")
    if neighbor_agreement < 0.4:
        reasons.append("wide vector distance distribution")
    return SimilarityConfidence(
        similarity_score=round(similarity_score, 6),
        confidence=round(confidence, 6),
        neighbor_count=len(matches),
        minimum_neighbors=minimum_neighbors,
        average_distance=round(average_distance, 6),
        distance_spread=round(distance_spread, 6),
        neighbor_agreement=round(neighbor_agreement, 6),
        reasons=reasons,
    )


def coverage_for_matches(matches: list[SimilarityMatch], *, minimum_neighbors: int) -> float:
    if minimum_neighbors <= 0:
        return 1.0 if matches else 0.0
    return round(min(1.0, len(matches) / minimum_neighbors), 6)


def distribution_for_matches(matches: list[SimilarityMatch]) -> SimilarityDistribution:
    """Deterministic neighbourhood shape — pure summary statistics, no ML."""
    if not matches:
        return SimilarityDistribution(
            count=0,
            best_similarity=0.0,
            worst_similarity=0.0,
            mean_similarity=0.0,
            min_distance=0.0,
            max_distance=0.0,
            mean_distance=0.0,
            distance_spread=0.0,
        )
    sims = [m.similarity for m in matches]
    dists = [m.distance for m in matches]
    return SimilarityDistribution(
        count=len(matches),
        best_similarity=round(max(sims), 6),
        worst_similarity=round(min(sims), 6),
        mean_similarity=round(sum(sims) / len(sims), 6),
        min_distance=round(min(dists), 6),
        max_distance=round(max(dists), 6),
        mean_distance=round(sum(dists) / len(dists), 6),
        distance_spread=round(max(dists) - min(dists), 6),
    )
