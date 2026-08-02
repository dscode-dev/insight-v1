"""Canonical Atlas intelligence contracts.

These models describe evidence and intelligence, never recommendations.  They
are immutable, strict on unknown fields, JSON serialisable, and independent of
all model-training and runtime activation paths.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from atlas.contracts import SourceRef
from atlas.intelligence.kernel import (
    INTELLIGENCE_SCHEMA_VERSION,
    Coverage,
    EvidenceID,
    EvidenceWindow,
    InsightID,
    RegimeID,
    SignalID,
    SimilarityID,
    TrendID,
    UnitScore,
    ensure_aware,
    utcnow,
)


class SignalType(str, enum.Enum):
    market = "market"
    form = "form"
    momentum = "momentum"
    behavior = "behavior"
    regime = "regime"
    similarity = "similarity"
    volatility = "volatility"


class SignalLifecycleStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    expired = "expired"
    weak = "weak"
    reinforced = "reinforced"
    conflicting = "conflicting"


class EvidenceType(str, enum.Enum):
    historical = "historical"
    market = "market"
    statistical = "statistical"
    regime = "regime"
    behavioral = "behavioral"


class BehaviorType(str, enum.Enum):
    low_scoring = "low_scoring"
    high_scoring = "high_scoring"
    explosive = "explosive"
    stagnant = "stagnant"
    draw_tendency = "draw_tendency"
    draw_resistance = "draw_resistance"
    favorite_dominance = "favorite_dominance"
    favorite_pressure = "favorite_pressure"
    favorite_instability = "favorite_instability"
    home_dominance = "home_dominance"
    away_resilience = "away_resilience"
    stable = "stable"
    volatile = "volatile"
    chaotic = "chaotic"
    market_agreement = "market_agreement"
    market_disagreement = "market_disagreement"
    market_uncertainty = "market_uncertainty"


class TrendDirection(str, enum.Enum):
    rising = "rising"
    falling = "falling"
    stable = "stable"
    mixed = "mixed"


class RegimeType(str, enum.Enum):
    league = "league"
    continental = "continental"
    international = "international"
    knockout = "knockout"
    high_volatility = "high_volatility"
    low_information = "low_information"


class MarketMovementDirection(str, enum.Enum):
    shortening = "shortening"
    drifting = "drifting"
    stable = "stable"
    mixed = "mixed"
    unavailable = "unavailable"


class IntelligenceNodeType(str, enum.Enum):
    signal = "signal"
    evidence = "evidence"
    behavior = "behavior"
    trend = "trend"
    memory = "memory"
    market = "market"
    uncertainty = "uncertainty"
    regime = "regime"


class IntelligenceEdgeType(str, enum.Enum):
    supports = "supports"
    weakens = "weakens"
    conflicts_with = "conflicts_with"
    explains = "explains"
    derived_from = "derived_from"
    increases_confidence = "increases_confidence"
    increases_uncertainty = "increases_uncertainty"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: EvidenceID = Field(default_factory=lambda: EvidenceID(uuid4()))
    evidence_type: EvidenceType
    source: str = Field(min_length=1, max_length=128)
    weight: UnitScore
    confidence: UnitScore
    description: str = Field(min_length=1, max_length=512)
    observed_at: datetime
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class UncertaintyInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    insight_id: InsightID = Field(default_factory=lambda: InsightID(uuid4()))
    uncertainty_score: UnitScore
    missing_signals: list[str] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    low_coverage: bool = False
    recommendations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class IntelligenceSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: SignalID = Field(default_factory=lambda: SignalID(uuid4()))
    signal_name: str = Field(min_length=1, max_length=96)
    signal_type: SignalType
    strength: UnitScore
    confidence: UnitScore
    uncertainty: UncertaintyInsight
    evidence: list[Evidence] = Field(default_factory=list)
    coverage: Coverage
    sources: list[SourceRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)

    @model_validator(mode="before")
    @classmethod
    def _drop_derived_counts(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                key: value
                for key, value in data.items()
                if key not in {"source_count", "evidence_count"}
            }
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_count(self) -> int:
        return len({source.source_id for source in self.sources})

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_count(self) -> int:
        return len(self.evidence)

    @model_validator(mode="after")
    def _coverage_sources_align(self) -> "IntelligenceSignal":
        if self.coverage.source_count != self.source_count:
            raise ValueError("coverage source_count must match distinct signal sources")
        return self


class SignalDependencyEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_signal: str = Field(min_length=1, max_length=128)
    child_signal: str = Field(min_length=1, max_length=128)
    relation: Literal["requires", "supports", "weakens"]
    parent_status: SignalLifecycleStatus | None = None
    confidence_effect: float = Field(ge=-1.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=512)


class SignalState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str = Field(min_length=1, max_length=160)
    signal_key: str = Field(min_length=1, max_length=128)
    signal_name: str = Field(min_length=1, max_length=128)
    signal_type: str = Field(min_length=1, max_length=64)
    status: SignalLifecycleStatus
    active: bool
    expired: bool = False
    weak: bool = False
    reinforced: bool = False
    conflicting: bool = False
    base_strength: UnitScore
    effective_strength: UnitScore
    base_confidence: UnitScore
    effective_confidence: UnitScore
    base_weight: UnitScore
    effective_weight: UnitScore
    signal_stability: UnitScore
    dependencies: list[str] = Field(default_factory=list)
    dependency_edges: list[SignalDependencyEdge] = Field(default_factory=list)
    reinforced_by: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    generated_at: datetime
    expires_at: datetime | None = None
    explanation: str = Field(min_length=1, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("generated_at", "expires_at")
    @classmethod
    def _aware_optional(cls, value: datetime | None) -> datetime | None:
        return ensure_aware(value) if value is not None else value


class SignalStateSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    states: list[SignalState] = Field(default_factory=list)
    strongest_signals: list[str] = Field(default_factory=list)
    weakest_signals: list[str] = Field(default_factory=list)
    expired_signals: list[str] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    reinforced_signals: list[str] = Field(default_factory=list)
    dependency_explanation: dict[str, list[str]] = Field(default_factory=dict)
    average_stability: UnitScore = 0.0
    average_effective_confidence: UnitScore = 0.0
    evidence: list[Evidence] = Field(default_factory=list)


class TrendInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_id: TrendID = Field(default_factory=lambda: TrendID(uuid4()))
    trend_type: str = Field(min_length=1, max_length=96)
    direction: TrendDirection
    strength: UnitScore
    confidence: UnitScore
    evidence: list[Evidence] = Field(default_factory=list)
    regime: RegimeID | None = None
    window: EvidenceWindow

    @model_validator(mode="before")
    @classmethod
    def _drop_derived_count(cls, data: Any) -> Any:
        if isinstance(data, dict) and "evidence_count" in data:
            return {key: value for key, value in data.items() if key != "evidence_count"}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_count(self) -> int:
        return len(self.evidence)


class RegimeInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    regime_id: RegimeID = Field(default_factory=lambda: RegimeID(uuid4()))
    regime_type: RegimeType
    confidence: UnitScore
    characteristics: list[str] = Field(default_factory=list)
    expected_behavior: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)


class MarketMovement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: MarketMovementDirection
    strength: UnitScore
    outcome: str | None = Field(default=None, max_length=32)


class MarketInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    insight_id: InsightID = Field(default_factory=lambda: InsightID(uuid4()))
    movement: MarketMovement
    volatility: UnitScore
    disagreement: UnitScore
    favorite_pressure: UnitScore
    implied_shift: float = Field(ge=-1.0, le=1.0)
    confidence: UnitScore


class SimilarMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    match_id: UUID
    competition: str
    kickoff_at: datetime
    home: str
    away: str
    similarity_score: UnitScore
    shared_patterns: list[str] = Field(default_factory=list)
    shared_signals: list[str] = Field(default_factory=list)
    shared_trends: list[str] = Field(default_factory=list)
    historical_outcome: str
    total_goals: int = Field(ge=0)

    @field_validator("kickoff_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)


class HistoricalOutcomeDistribution(BaseModel):
    """Observed neighbor counts, never predictive probabilities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    home_wins: int = Field(ge=0)
    draws: int = Field(ge=0)
    away_wins: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def _drop_derived_sample_size(cls, data: Any) -> Any:
        if isinstance(data, dict) and "sample_size" in data:
            return {key: value for key, value in data.items() if key != "sample_size"}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sample_size(self) -> int:
        return self.home_wins + self.draws + self.away_wins


class SimilarityInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    similarity_id: SimilarityID = Field(
        default_factory=lambda: SimilarityID(uuid4())
    )
    similar_matches: list[SimilarMatch] = Field(default_factory=list)
    similarity_score: UnitScore
    minimum_similarity: UnitScore
    maximum_similarity: UnitScore
    similarity_threshold: UnitScore
    actual_neighbor_count: int = Field(ge=0)
    outcome_distribution: HistoricalOutcomeDistribution
    shared_patterns: list[str] = Field(default_factory=list)
    shared_signals: list[str] = Field(default_factory=list)
    shared_trends: list[str] = Field(default_factory=list)
    trend_distribution: dict[str, int] = Field(default_factory=dict)
    regime_distribution: dict[str, int] = Field(default_factory=dict)
    average_goals: float = Field(ge=0.0)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: UnitScore


class PatternHistory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    occurrences: int = Field(ge=0)
    sample_size: int = Field(ge=0)
    competition_distribution: dict[str, int] = Field(default_factory=dict)
    regime_distribution: dict[str, int] = Field(default_factory=dict)


class BehaviorPattern(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: UUID = Field(default_factory=uuid4)
    type: BehaviorType
    confidence: UnitScore
    uncertainty: UnitScore
    evidence: list[Evidence] = Field(default_factory=list)
    regime: RegimeID | None = None
    strength: UnitScore
    history: PatternHistory
    cooccurring_patterns: list[BehaviorType] = Field(default_factory=list)


class IntelligenceNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    node_type: IntelligenceNodeType
    label: str = Field(min_length=1, max_length=160)
    confidence: UnitScore
    attributes: dict[str, Any] = Field(default_factory=dict)


class IntelligenceEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_node_id: str = Field(min_length=1, max_length=128)
    target_node_id: str = Field(min_length=1, max_length=128)
    edge_type: IntelligenceEdgeType
    weight: UnitScore
    rationale: str = Field(min_length=1, max_length=512)


class IntelligenceGraph(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: list[IntelligenceNode] = Field(default_factory=list)
    edges: list[IntelligenceEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_graph(self) -> "IntelligenceGraph":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("intelligence graph node IDs must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source_node_id not in known or edge.target_node_id not in known:
                raise ValueError("intelligence graph edge references unknown node")
        return self


class ReasoningStatement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=1, max_length=96)
    conclusion: str = Field(min_length=1, max_length=512)
    confidence: UnitScore
    supporting_node_ids: list[str] = Field(default_factory=list)
    confidence_effect: float = Field(ge=-1.0, le=1.0)
    uncertainty_effect: float = Field(ge=-1.0, le=1.0)


class ConflictInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conflict_id: str = Field(min_length=1, max_length=128)
    severity: UnitScore
    description: str = Field(min_length=1, max_length=512)
    node_ids: list[str] = Field(default_factory=list)
    uncertainty_effect: UnitScore


class ConfidenceExplanation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: Literal["low", "medium", "high"]
    score: UnitScore
    positive_factors: list[str] = Field(default_factory=list)
    limiting_factors: list[str] = Field(default_factory=list)


class UncertaintyExplanation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    score: UnitScore
    reasons: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    reducing_factors: list[str] = Field(default_factory=list)


class ReasoningInsight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statements: list[ReasoningStatement] = Field(default_factory=list)
    behavior_explanations: dict[str, list[str]] = Field(default_factory=dict)
    top_supporting_evidence: list[str] = Field(default_factory=list)


class AtlasIntelligenceReport(BaseModel):
    """Atlas's primary output: evidence-backed intelligence, not prediction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: InsightID = Field(default_factory=lambda: InsightID(uuid4()))
    schema_version: str = INTELLIGENCE_SCHEMA_VERSION
    match_id: UUID | None = None
    competition_id: UUID | None = None
    as_of: datetime
    signals: list[IntelligenceSignal] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    trends: list[TrendInsight] = Field(default_factory=list)
    regime: RegimeInsight | None = None
    market: MarketInsight | None = None
    head_to_head: Any | None = None
    home_team_memory: Any | None = None
    away_team_memory: Any | None = None
    memory_confidence: Any | None = None
    memory: Any | None = None
    similarity: SimilarityInsight | None = None
    behaviors: list[BehaviorPattern] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    reasoning: ReasoningInsight | None = None
    graph: IntelligenceGraph | None = None
    conflicts: list[ConflictInsight] = Field(default_factory=list)
    confidence_explanation: ConfidenceExplanation | None = None
    uncertainty_explanation: UncertaintyExplanation | None = None
    vector_contexts: list[Any] = Field(default_factory=list)
    vector_neighbors: int = Field(default=0, ge=0)
    vector_confidence: Any | None = None
    explorer_memory: Any | None = None
    explorer_behaviors: list[Any] = Field(default_factory=list)
    explorer_signals: list[Any] = Field(default_factory=list)
    signal_states: list[SignalState] = Field(default_factory=list)
    signal_state: SignalStateSummary | None = None
    strongest_signals: list[str] = Field(default_factory=list)
    weakest_signals: list[str] = Field(default_factory=list)
    expired_signals: list[str] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    reinforced_signals: list[str] = Field(default_factory=list)
    dependency_explanation: dict[str, list[str]] = Field(default_factory=dict)
    ingestion_lineage: dict[str, Any] | None = None
    uncertainty: UncertaintyInsight
    runtime: Any | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("as_of", "created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_aware(value)

    @model_validator(mode="before")
    @classmethod
    def _drop_derived_counts(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                key: value
                for key, value in data.items()
                if key not in {"source_count", "evidence_count"}
            }
        return data

    @model_validator(mode="after")
    def _evidence_is_unique(self) -> "AtlasIntelligenceReport":
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("report evidence_id values must be unique")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_count(self) -> int:
        return len(self.evidence)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_count(self) -> int:
        return len(
            {
                source.source_id
                for signal in self.signals
                for source in signal.sources
            }
        )
