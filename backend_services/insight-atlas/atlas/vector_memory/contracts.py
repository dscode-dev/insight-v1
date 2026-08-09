"""Contracts for deterministic local vector memory."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from atlas.intelligence.contracts import RegimeType
from atlas.intelligence.kernel import UnitScore, ensure_aware

EMBEDDING_DIMENSIONS = 32
EMBEDDING_VERSION = "atlas-memory-embedding-v1"

# ATLAS-SIM-A: v2 coexists with v1 (FROZEN per ATLAS_V1_FROZEN.md) rather
# than replacing it — a distinct version string, dimension count, storage
# column (atlas.atlas_vector_memory.embedding_v2, migration 0018) and
# contract class. Nothing about MemoryEmbedding/EMBEDDING_VERSION above
# changes; old v1 vectors stay exactly as they were.
EMBEDDING_DIMENSIONS_V2 = 37
EMBEDDING_VERSION_V2 = "atlas-memory-embedding-v2"


class MemoryEmbedding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    vector_id: UUID
    source_match_id: str
    competition: str
    regime: RegimeType
    home_team: str
    away_team: str
    behavior: list[str] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    market_available: bool
    uncertainty: UnitScore
    embedding_version: str = EMBEDDING_VERSION
    embedding: tuple[float, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)

    @model_validator(mode="after")
    def _dimension(self) -> MemoryEmbedding:
        if len(self.embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"embedding must contain {EMBEDDING_DIMENSIONS} dimensions"
            )
        return self


class MemoryEmbeddingV2(BaseModel):
    """Same shape as `MemoryEmbedding`, sized for the ATLAS-SIM-A v2
    layout (37 dims — see `atlas/vector_memory/embedding.py`). A
    separate class rather than a shared base because `MemoryEmbedding`'s
    dimension check is intentionally hardcoded to the frozen v1 constant
    — subclassing it would risk that guard silently drifting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector_id: UUID
    source_match_id: str
    competition: str
    regime: RegimeType
    home_team: str
    away_team: str
    behavior: list[str] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    market_available: bool
    uncertainty: UnitScore
    embedding_version: str = EMBEDDING_VERSION_V2
    embedding: tuple[float, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)

    @model_validator(mode="after")
    def _dimension(self) -> MemoryEmbeddingV2:
        if len(self.embedding) != EMBEDDING_DIMENSIONS_V2:
            raise ValueError(
                f"embedding must contain {EMBEDDING_DIMENSIONS_V2} dimensions"
            )
        return self


class VectorNeighbor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    vector_id: UUID
    source_match_id: str
    competition: str
    regime: RegimeType
    home_team: str
    away_team: str
    similarity: UnitScore
    shared_behaviors: list[str] = Field(default_factory=list)
    shared_trends: list[str] = Field(default_factory=list)
    shared_signals: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class VectorConfidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    average_similarity: UnitScore
    vector_agreement: UnitScore
    coverage: UnitScore
    confidence: UnitScore
    threshold: UnitScore
    reasons: list[str] = Field(default_factory=list)


class VectorMemoryInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contexts: list[VectorNeighbor] = Field(default_factory=list)
    neighbor_count: int = Field(ge=0)
    confidence: VectorConfidence
    deterministic_memory_preserved: bool = True

