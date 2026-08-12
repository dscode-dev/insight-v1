"""Canonical, serializable replay/evaluation contracts (ATLAS-BACKTEST-A).

Runtime inputs (ReplayScenario/ReplayStep) are dataclasses holding the
production `TrendInputs`; every RESULT object is a frozen pydantic model so it
serializes deterministically for reports, regression and artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from atlas.trends.models import TrendInputs


# --------------------------------------------------------------------------- #
# Runtime scenario (not serialized — carries the production TrendInputs)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReplayStep:
    index: int
    inputs: TrendInputs
    label: str = ""


@dataclass(frozen=True)
class ReplayScenario:
    scenario_id: str
    source: str  # match | competition | season | dataset | fixture
    steps: list[ReplayStep] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Serializable evaluation results
# --------------------------------------------------------------------------- #
class TrendEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_index: int
    trend_type: str
    category: str
    agent: str | None = None
    strength: float
    confidence: float
    direction: int


class DetectorEvaluation(BaseModel):
    """Generic per-(agent, trend_type) detector metrics — no detector-specific code."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str
    trend_type: str
    executions: int
    positive_detections: int
    average_confidence: float
    average_strength: float
    average_latency_ms: float
    historical_coverage: float  # steps with ≥1 detection / steps executed


class SimilarityEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_index: int
    neighbor_count: int
    confidence: float
    agreement: float


class BehaviorEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_index: int
    behavior_trends: int  # narrative/behaviour-category trends at this step


class ReplayQuality(BaseModel):
    """Global consistency metrics (Stage 7). NO precision/recall (next sprint)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    replay_completion: float
    pipeline_completion: float
    detector_stability: float
    similarity_consistency: float
    signal_consistency: float
    behavior_consistency: float
    reasoning_consistency: float
    trend_consistency: float


class ReplayReport(BaseModel):
    """Deterministic, timestamped timelines (Stage 5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_timeline: list[dict] = Field(default_factory=list)
    detector_timeline: list[dict] = Field(default_factory=list)
    similarity_timeline: list[dict] = Field(default_factory=list)
    behavior_timeline: list[dict] = Field(default_factory=list)
    signal_timeline: list[dict] = Field(default_factory=list)
    reasoning_timeline: list[dict] = Field(default_factory=list)
    operational_events: list[dict] = Field(default_factory=list)


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    source: str
    steps_total: int
    steps_executed: int
    trends: list[TrendEvaluation] = Field(default_factory=list)
    detectors: list[DetectorEvaluation] = Field(default_factory=list)
    similarity: list[SimilarityEvaluation] = Field(default_factory=list)
    behavior: list[BehaviorEvaluation] = Field(default_factory=list)
    quality: ReplayQuality
    report: ReplayReport
    # Stable fingerprint of the emitted trends — same inputs ⇒ same hash.
    deterministic_hash: str


class RegressionDiff(BaseModel):
    """Difference between a baseline and a candidate replay (Stage 6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identical: bool
    baseline_hash: str
    candidate_hash: str
    new_detections: list[dict] = Field(default_factory=list)
    lost_detections: list[dict] = Field(default_factory=list)
    confidence_changes: list[dict] = Field(default_factory=list)
    strength_changes: list[dict] = Field(default_factory=list)
    trend_changes: list[dict] = Field(default_factory=list)


class ReplayExecution(BaseModel):
    """Async replay job envelope + deterministic lifecycle (Stage 4/8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    scenario_id: str
    source: str
    # submitted → queued → running → completed | failed | cancelled
    status: str = "submitted"
    dataset_id: str = ""
    requester: str = ""
    submitted_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    replay_hash: str | None = None
    artifact_keys: list[str] = Field(default_factory=list)
    result: ReplayResult | None = None
    error: str | None = None


class ReplayArtifacts(BaseModel):
    """Reproducible, persisted replay artifacts (Stage 5/8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    replay_hash: str
    report: ReplayReport
    detectors: list[DetectorEvaluation] = Field(default_factory=list)
    trend_timeline: list[dict] = Field(default_factory=list)
    operational_events: list[dict] = Field(default_factory=list)
    regression: RegressionDiff | None = None


# --------------------------------------------------------------------------- #
# Quality Gate (ATLAS-BACKTEST-B)
# --------------------------------------------------------------------------- #
class DetectorReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str
    trend_type: str
    executions: int
    positive_detections: int
    negative_detections: int
    suppressed_detections: int
    average_confidence: float
    average_strength: float
    average_latency_ms: float
    historical_coverage: float
    detector_stability: float


class StageEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    executions: int
    inputs_present: int
    detections: int


class QualityReport(BaseModel):
    """Deterministic quality metrics. precision/recall/F1/FP/FN are computed ONLY
    against a reference (baseline) replay; `None` when no reference — never estimated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    has_reference: bool
    precision: float | None = None
    recall: float | None = None
    f1_score: float | None = None
    false_positives: int | None = None
    false_negatives: int | None = None
    detector_agreement: float
    detector_disagreement: float
    similarity_usefulness: float
    reasoning_consistency: float
    trend_stability: float


class PromotionReport(BaseModel):
    """Recommendation only — never auto-promotes, never recalibrates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str
    trend_type: str
    verdict: str  # Approved | Warning | Rejected
    reasons: list[str] = Field(default_factory=list)


class ExplainabilityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str
    trend_type: str
    verdict: str
    explanation: list[str] = Field(default_factory=list)


class RegressionReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quality_regression: bool
    confidence_regression: bool
    detector_regression: bool
    trend_regression: bool
    similarity_regression: bool
    reasoning_regression: bool
    diff: RegressionDiff


class QualityEvaluation(BaseModel):
    """The full Quality Gate output for one replay (Stage 1-6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    replay_hash: str
    detectors: list[DetectorReport] = Field(default_factory=list)
    stages: list[StageEvaluation] = Field(default_factory=list)
    quality: QualityReport
    promotions: list[PromotionReport] = Field(default_factory=list)
    explainability: list[ExplainabilityReport] = Field(default_factory=list)
    regression: RegressionReport | None = None
