"""Shared primitives for Atlas's canonical intelligence language.

The kernel is deliberately side-effect free.  It contains identity, bounded
measurement, coverage, time-window and request-context types shared by every
future intelligence provider.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, NewType
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SignalID = NewType("SignalID", UUID)
InsightID = NewType("InsightID", UUID)
TrendID = NewType("TrendID", UUID)
RegimeID = NewType("RegimeID", UUID)
EvidenceID = NewType("EvidenceID", UUID)
SimilarityID = NewType("SimilarityID", UUID)

UnitScore = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveCount = Annotated[int, Field(ge=0)]

INTELLIGENCE_SCHEMA_VERSION = "atlas.intelligence.v1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class Coverage(BaseModel):
    """How much of the expected evidence surface was observed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected: PositiveCount = 0
    observed: PositiveCount = 0
    ratio: UnitScore = 0.0
    source_count: PositiveCount = 0

    @model_validator(mode="after")
    def _consistent(self) -> "Coverage":
        if self.expected and self.observed > self.expected:
            raise ValueError("observed coverage cannot exceed expected coverage")
        expected_ratio = self.observed / self.expected if self.expected else 0.0
        if abs(self.ratio - expected_ratio) > 1e-6:
            raise ValueError("coverage ratio must equal observed / expected")
        return self


class EvidenceWindow(BaseModel):
    """Inclusive time window over which evidence was measured."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)

    @model_validator(mode="after")
    def _ordered(self) -> "EvidenceWindow":
        if self.end < self.start:
            raise ValueError("evidence window end must not precede start")
        return self

    @property
    def seconds(self) -> int:
        return max(0, int((self.end - self.start).total_seconds()))


class IntelligenceMetadata(BaseModel):
    """Common metadata available on canonical intelligence aggregates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence: UnitScore
    uncertainty: UnitScore
    coverage: Coverage
    timestamp: datetime = Field(default_factory=utcnow)
    source_count: PositiveCount = 0
    evidence_count: PositiveCount = 0

    @field_validator("timestamp")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class IntelligenceContext(BaseModel):
    """Immutable request context passed to provider interfaces.

    It carries identity and as-of metadata only; providers obtain their own
    evidence through their ports.  ``attributes`` is routing context, never a
    bag of unvalidated provider payloads.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    match_id: UUID | None = None
    competition_id: UUID | None = None
    as_of: datetime
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("as_of")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)
