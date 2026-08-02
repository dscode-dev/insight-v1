"""Oracle — online pgvector similarity detector (ATLAS-VECTOR-B).

Activates the two historical trend types that were reserved in the taxonomy:

  * ``historical_similarity`` — this developing match resembles a coherent set
    of prior matches (nearest vectors passed every gate).
  * ``historical_pattern``    — the resemblance is not only close but *tight*
    (dense, high-agreement neighbourhood), i.e. a recurring pattern.

The detector is a PURE, SYNCHRONOUS consumer of a precomputed
``SimilarityContext`` attached to ``TrendInputs.similarity`` by
``TrendIntelligencePipeline`` (the async pgvector query runs there, not here).
It never talks to a database, never uses an in-memory index, and never falls
back to a degraded guess: if any gate fails it emits nothing.

``HistoricalDeviationDetector`` (atlas/trends/oracle.py) is unchanged and keeps
running alongside this detector in the same historical engine.
"""

from __future__ import annotations

from atlas.similarity.contracts import SimilarityContext, SimilarityMatch
from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class OracleSimilarityDetector:
    """Emit historical similarity/pattern trends from online pgvector search.

    Deterministic gates (Stage 4) — a trend is emitted ONLY when ALL pass:
      * minimum_similarity   — best neighbour similarity ≥ the query threshold
      * minimum_neighbors    — neighbour_count ≥ the query minimum
      * neighbour agreement  — distance distribution is tight (≥ agreement gate)
      * compatible versions  — every neighbour shares the query embedding +
                               feature-schema version
      * compatible domain    — every neighbour matches the query competition /
                               season / market_type / match_phase WHEN the query
                               declared them (unknown query facet = not gated)

    ``pattern_*`` gates are strictly tighter than the similarity gates, so
    ``historical_pattern`` is a superset condition of ``historical_similarity``.
    """

    def __init__(
        self,
        *,
        minimum_agreement: float = 0.40,
        pattern_min_neighbors: int = 5,
        pattern_min_agreement: float = 0.60,
        top_neighbors: int = 5,
    ) -> None:
        self._min_agreement = minimum_agreement
        self._pattern_min_neighbors = pattern_min_neighbors
        self._pattern_min_agreement = pattern_min_agreement
        self._top_neighbors = top_neighbors

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        result = inputs.similarity
        if result is None or not result.matches:
            return []

        # Domain/version compatibility gate — every returned neighbour must be
        # compatible with the query facets that were actually declared.
        compatible = [m for m in result.matches if self._compatible(m, result)]
        if not compatible:
            return []

        confidence = result.confidence
        best_similarity = max(m.similarity for m in compatible)
        neighbor_count = len(compatible)

        # Similarity gates.
        if best_similarity < result.minimum_similarity:
            return []
        if neighbor_count < confidence.minimum_neighbors:
            return []
        if confidence.neighbor_agreement < self._min_agreement:
            return []

        trends: list[Trend] = [
            self._trend(
                inputs,
                result,
                compatible,
                trend_type=TrendType.historical_similarity,
                best_similarity=best_similarity,
            )
        ]

        # Pattern gate — a coherent, recurring neighbourhood (strictly tighter).
        if (
            neighbor_count >= self._pattern_min_neighbors
            and confidence.neighbor_agreement >= self._pattern_min_agreement
        ):
            trends.append(
                self._trend(
                    inputs,
                    result,
                    compatible,
                    trend_type=TrendType.historical_pattern,
                    best_similarity=best_similarity,
                )
            )
        return trends

    # -- gates ----------------------------------------------------------------

    @staticmethod
    def _compatible(match: SimilarityMatch, result: SimilarityContext) -> bool:
        filters = result.filters
        if match.embedding_version != filters.embedding_version:
            return False
        # Each optional facet is gated ONLY when the query declared it.
        checks = (
            (filters.feature_schema_version, match.feature_schema_version),
            (filters.competition, match.competition),
            (filters.season, match.season),
            (filters.market_type, match.market_type),
            (filters.match_phase, match.match_phase),
        )
        for wanted, got in checks:
            if wanted is not None and got != wanted:
                return False
        return True

    # -- trend construction ---------------------------------------------------

    def _trend(
        self,
        inputs: TrendInputs,
        result: SimilarityContext,
        matches: list[SimilarityMatch],
        *,
        trend_type: TrendType,
        best_similarity: float,
    ) -> Trend:
        confidence = result.confidence
        is_pattern = trend_type == TrendType.historical_pattern
        return Trend(
            trend_type=trend_type,
            category=TrendCategory.oracle,
            canonical_match_id=inputs.canonical_match_id,
            competition_id=inputs.competition_id,
            minute=inputs.minute,
            # Pattern strength leans on tightness; similarity strength on the
            # combined similarity score. Both bounded [0, 1].
            strength=_clamp(
                confidence.neighbor_agreement if is_pattern else confidence.similarity_score
            ),
            confidence=_clamp(confidence.confidence),
            direction=0,  # historical resemblance has no market direction
            evidence=self._evidence(result, matches, best_similarity, trend_type),
        )

    def _evidence(
        self,
        result: SimilarityContext,
        matches: list[SimilarityMatch],
        best_similarity: float,
        trend_type: TrendType,
    ) -> dict:
        confidence = result.confidence
        filters = result.filters
        top = matches[: self._top_neighbors]
        kind = "pattern" if trend_type == TrendType.historical_pattern else "resemblance"
        summary = (
            f"{len(matches)} compatible historical neighbours "
            f"(best similarity {best_similarity:.3f}, "
            f"agreement {confidence.neighbor_agreement:.3f}) "
            f"establish a {kind} under embedding {filters.embedding_version}."
        )
        return {
            # matched event ids
            "matched_event_ids": [m.match_id for m in matches],
            # distances / similarities
            "best_similarity": round(best_similarity, 6),
            "similarity_score": confidence.similarity_score,
            "average_distance": confidence.average_distance,
            "distance_spread": confidence.distance_spread,
            "neighbor_agreement": confidence.neighbor_agreement,
            # counts / confidence
            "neighbor_count": confidence.neighbor_count,
            "minimum_neighbors": confidence.minimum_neighbors,
            "minimum_similarity": result.minimum_similarity,
            "confidence": confidence.confidence,
            # versions (explainability)
            "embedding_version": filters.embedding_version,
            "feature_schema_version": filters.feature_schema_version,
            "signal_catalog_version": filters.signal_catalog_version,
            "behavior_catalog_version": filters.behavior_catalog_version,
            "competition": filters.competition,
            "season": filters.season,
            "market_type": filters.market_type,
            "match_phase": filters.match_phase,
            # reasoning + top contributing neighbours
            "reasoning_summary": summary,
            "gate_reasons": confidence.reasons,
            "top_neighbors": [
                {
                    "match_id": m.match_id,
                    "similarity": m.similarity,
                    "distance": m.distance,
                    "competition": m.competition,
                    "season": m.season,
                }
                for m in top
            ],
        }
