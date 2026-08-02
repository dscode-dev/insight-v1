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
    def _dimension(self) -> "MemoryEmbedding":
        if len(self.embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"embedding must contain {EMBEDDING_DIMENSIONS} dimensions"
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

