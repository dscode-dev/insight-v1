"""Deterministic hierarchical football-memory contracts."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atlas.intelligence.contracts import Evidence, RegimeType, SimilarMatch
from atlas.intelligence.kernel import UnitScore, ensure_aware


class MemoryLayer(str, enum.Enum):
    head_to_head = "head_to_head"
    home_team = "home_team"
    away_team = "away_team"
    competition = "competition"
    behavior = "behavior"
    generic_similarity = "generic_similarity"


class TeamRoleBehavior(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    matches: int = Field(ge=0)
    wins: int = Field(ge=0)
    draws: int = Field(ge=0)
    losses: int = Field(ge=0)
    goals_for: float = Field(ge=0)
    goals_against: float = Field(ge=0)


class TeamMemoryProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    team_id: UUID
    team: str
    competition: str
    regime: RegimeType
    matches: int = Field(ge=0)
    draw_rate: UnitScore
    goals_for: float = Field(ge=0)
    goals_against: float = Field(ge=0)
    home_behavior: TeamRoleBehavior
    away_behavior: TeamRoleBehavior
    volatility: UnitScore
    trends: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class HeadToHeadMemory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    home_team_id: UUID
    away_team_id: UUID
    home_team: str
    away_team: str
    competition: str
    matches: int = Field(ge=0)
    home_team_wins: int = Field(ge=0)
    away_team_wins: int = Field(ge=0)
    draws: int = Field(ge=0)
    goals: float = Field(ge=0)
    trends: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class CompetitionMemory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    competition: str
    regime: RegimeType
    matches: int = Field(ge=0)
    draw_rate: UnitScore
    goals_per_match: float = Field(ge=0)
    volatility: UnitScore
    trends: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class BehaviorMemory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    matches: list[SimilarMatch] = Field(default_factory=list)
    threshold: UnitScore
    average_similarity: UnitScore
    shared_behaviors: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class MemoryConfidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    h2h_coverage: UnitScore
    home_team_coverage: UnitScore
    away_team_coverage: UnitScore
    competition_coverage: UnitScore
    historical_depth: UnitScore
    overall: UnitScore
    uncertainty: UnitScore
    reasons: list[str] = Field(default_factory=list)


class HierarchicalMemoryInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query_match_id: UUID
    home_team: str
    away_team: str
    competition: str
    as_of: datetime
    retrieval_order: list[MemoryLayer]
    head_to_head: HeadToHeadMemory
    home_team_memory: TeamMemoryProfile
    away_team_memory: TeamMemoryProfile
    competition_memory: CompetitionMemory
    behavior_memory: BehaviorMemory
    generic_similarity: list[SimilarMatch] = Field(default_factory=list)
    memory_confidence: MemoryConfidence
    evidence: list[Evidence] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)

