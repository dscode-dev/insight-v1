"""Immutable Explorer -> Atlas intelligence contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atlas.intelligence.contracts import RegimeType
from atlas.intelligence.kernel import ensure_aware
from atlas.vector_memory.contracts import EMBEDDING_DIMENSIONS, EMBEDDING_VERSION

INGEST_SCHEMA_VERSION = "explorer-atlas.ingest.v1"


class IngestLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generation_id: str = Field(min_length=1, max_length=160)
    source_system: Literal["insight-explorer"] = "insight-explorer"
    source_path: str = Field(min_length=1, max_length=512)
    source_checksum: str = Field(pattern=r"^(sha256:)?[0-9a-f]{64}$")
    feature_time_policy: Literal["strictly_before_kickoff"]
    producer_version: str = Field(min_length=1, max_length=64)


class _IngestRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["explorer-atlas.ingest.v1"] = INGEST_SCHEMA_VERSION
    record_id: UUID
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observed_at: datetime
    lineage: IngestLineage

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class AtlasMemoryIngest(_IngestRecord):
    competition: str = Field(min_length=1, max_length=128)
    home_team: str = Field(min_length=1, max_length=128)
    away_team: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _context_matches(self) -> "AtlasMemoryIngest":
        if self.payload.get("competition") != self.competition:
            raise ValueError("memory competition mismatch")
        if self.payload.get("home_team_memory", {}).get("team_id") != self.home_team:
            raise ValueError("memory home team mismatch")
        if self.payload.get("away_team_memory", {}).get("team_id") != self.away_team:
            raise ValueError("memory away team mismatch")
        return self


class AtlasBehaviorIngest(_IngestRecord):
    competition: str = Field(min_length=1, max_length=128)
    behavior: str = Field(min_length=1, max_length=96)
    confidence: float = Field(ge=0, le=1)
    payload: dict[str, Any]


class AtlasSignalIngest(_IngestRecord):
    competition: str = Field(min_length=1, max_length=128)
    signal_family: Literal["context", "statistics", "trend"]
    payload: dict[str, Any]


class AtlasVectorIngest(_IngestRecord):
    source_match_id: str = Field(min_length=1, max_length=160)
    competition: str = Field(min_length=1, max_length=128)
    regime: RegimeType
    home_team: str = Field(min_length=1, max_length=128)
    away_team: str = Field(min_length=1, max_length=128)
    behavior: list[str] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    market_available: bool
    uncertainty: float = Field(ge=0, le=1)
    embedding_version: Literal["atlas-memory-embedding-v1"] = EMBEDDING_VERSION
    embedding: tuple[float, ...]

    @model_validator(mode="after")
    def _dimension(self) -> "AtlasVectorIngest":
        if len(self.embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"embedding must contain {EMBEDDING_DIMENSIONS} dimensions"
            )
        return self


class AtlasIngestionBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["explorer-atlas.ingest.v1"] = INGEST_SCHEMA_VERSION
    batch_id: UUID
    generation_id: str = Field(min_length=1, max_length=160)
    source_system: Literal["insight-explorer"] = "insight-explorer"
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime
    memories: list[dict[str, Any]] = Field(default_factory=list)
    behaviors: list[dict[str, Any]] = Field(default_factory=list)
    vectors: list[dict[str, Any]] = Field(default_factory=list)
    signals: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)
