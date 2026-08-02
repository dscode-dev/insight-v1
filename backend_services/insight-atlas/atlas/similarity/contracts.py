"""Canonical production vector similarity contracts.

These contracts are intentionally domain-neutral infrastructure. Oracle,
Atlas Intelligence and future ML components can consume them, but no Oracle or
trend semantics are emitted here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atlas.intelligence.kernel import UnitScore, ensure_aware
from atlas.vector_memory.contracts import EMBEDDING_DIMENSIONS, EMBEDDING_VERSION


class TimeWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime | None = None
    end: datetime | None = None

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return ensure_aware(value) if value is not None else None

    @model_validator(mode="after")
    def _ordered(self) -> "TimeWindow":
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("time_window.start must be before time_window.end")
        return self


class SimilarityFilters(BaseModel):
    """Version and domain filters for safe vector comparisons.

    `embedding_version` is mandatory for production online search. Additional
    schema/catalog filters are optional for backward compatibility with already
    persisted deterministic vectors.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    embedding_version: str = EMBEDDING_VERSION
    feature_schema_version: str | None = None
    signal_catalog_version: str | None = None
    behavior_catalog_version: str | None = None
    competition: str | None = None
    season: str | None = None
    market_type: str | None = None
    match_phase: str | None = None
    # ATLAS-SIMILARITY-B: regime scope, so the canonical service can reproduce
    # the regime-scoped causal memory query (was PgVectorMemoryRepository.search).
    regime: str | None = None
    time_window: TimeWindow | None = None
    exclude_match_id: str | None = None

    @field_validator("embedding_version")
    @classmethod
    def _embedding_version_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("embedding_version is required for similarity search")
        return value.strip()


class SimilaritySearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    embedding: tuple[float, ...]
    filters: SimilarityFilters = Field(default_factory=SimilarityFilters)
    top_k: int = Field(default=25, ge=1, le=250)
    minimum_similarity: UnitScore = 0.72
    minimum_neighbors: int = Field(default=3, ge=1, le=250)

    @model_validator(mode="after")
    def _dimension(self) -> "SimilaritySearchRequest":
        if len(self.embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"embedding must contain {EMBEDDING_DIMENSIONS} dimensions"
            )
        return self


class SimilarityMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    vector_id: UUID
    match_id: str
    similarity: UnitScore
    distance: float = Field(ge=0.0)
    embedding_version: str
    feature_schema_version: str | None = None
    signal_catalog_version: str | None = None
    behavior_catalog_version: str | None = None
    competition: str | None = None
    season: str | None = None
    market_type: str | None = None
    match_phase: str | None = None
    metadata: dict = Field(default_factory=dict)
    explanation: list[str] = Field(default_factory=list)


class SimilarityConfidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    similarity_score: UnitScore
    confidence: UnitScore
    neighbor_count: int = Field(ge=0)
    minimum_neighbors: int = Field(ge=1)
    average_distance: float = Field(ge=0.0)
    distance_spread: float = Field(ge=0.0)
    neighbor_agreement: UnitScore
    reasons: list[str] = Field(default_factory=list)


class SimilaritySearchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    matches: list[SimilarityMatch] = Field(default_factory=list)
    confidence: SimilarityConfidence
    filters: SimilarityFilters
    top_k: int
    minimum_similarity: UnitScore


class SimilarityDistribution(BaseModel):
    """Deterministic summary shape of a neighbourhood (pure statistics)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int = Field(ge=0)
    best_similarity: UnitScore
    worst_similarity: UnitScore
    mean_similarity: UnitScore
    min_distance: float = Field(ge=0.0)
    max_distance: float = Field(ge=0.0)
    mean_distance: float = Field(ge=0.0)
    distance_spread: float = Field(ge=0.0)


class SimilarityContext(BaseModel):
    """Canonical, reusable similarity domain object (ATLAS-SIMILARITY-A).

    A SUPERSET of SimilaritySearchResult (it keeps ``matches`` / ``confidence`` /
    ``filters`` / ``top_k`` / ``minimum_similarity`` so existing consumers read it
    unchanged) plus first-class ``agreement`` / ``coverage`` / ``distribution`` /
    ``reasoning`` / ``metadata`` and promoted version fields. Every intelligence
    engine — not just the Oracle — can consume this.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # -- compatibility surface (SimilaritySearchResult shape) --
    matches: list[SimilarityMatch] = Field(default_factory=list)
    confidence: SimilarityConfidence
    filters: SimilarityFilters
    top_k: int
    minimum_similarity: UnitScore

    # -- first-class similarity facets --
    agreement: UnitScore
    coverage: UnitScore
    distribution: SimilarityDistribution
    reasoning: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    # -- promoted version provenance --
    embedding_version: str
    feature_schema_version: str | None = None
    signal_catalog_version: str | None = None
    behavior_catalog_version: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.matches
