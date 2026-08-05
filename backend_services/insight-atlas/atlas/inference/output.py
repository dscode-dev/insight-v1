"""ContextOutput — the unified result of one Atlas inference.

Sprint 0 contract alignment:
  * Adds `output_id`, `model_name`, `sport`, `competition_id`,
    `context_type` (canonical alias for `family`).
  * Adds Pydantic aliases so Sprint 0 names (`confidence`,
    `explanation`, `contributing_features`, `created_at`) deserialise
    the same payload as the internal names (`context_confidence`,
    `headline`, `top_factors`, `generated_at`).
  * Adds a HARD GUARD that rejects any metric key matching a betting /
    prediction vocabulary. The guard runs in `model_validator` so it
    fires at deserialisation AND construction — no future commit can
    sneak `win_probability` into `metrics` without the test suite
    failing.

The class explicitly does NOT carry any field for win-probability,
recommendation, or pick. Adding one would require changing this file —
making the rule reviewable in code review.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from atlas.contracts import FeatureWindowOrigin, SourceRef
from atlas.contracts.no_prediction import (
    FORBIDDEN_METRIC_PATTERNS,
    assert_no_prediction_keys,
)

# ---------------------------------------------------------------------------
# Anti-prediction deny-list
# ---------------------------------------------------------------------------
#
# The rule itself now lives in `atlas/contracts/no_prediction.py` — it is
# shared with the trend wire contract and the intelligence report, which
# are Atlas's REAL public surfaces and were previously unguarded (this
# module only ever protected ContextOutput). Re-exported here under the
# original private names so existing callers/tests keep working.

_FORBIDDEN_METRIC_PATTERNS = FORBIDDEN_METRIC_PATTERNS


def _assert_no_prediction_keys(metrics: dict[str, Any]) -> None:
    assert_no_prediction_keys(metrics, where="ContextOutput.metrics")


class Factor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature: str
    contribution: float

    @field_validator("contribution")
    @classmethod
    def _round_contribution(cls, v: float) -> float:
        return float(round(v, 6))


class ContextOutput(BaseModel):
    """Wire model. Serialised verbatim by the REST API and as the payload
    of ML_CONTEXT events."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # --- Sprint 0 contract additions ---
    output_id: UUID = Field(default_factory=uuid4)
    sport: str = Field(default="football")
    competition_id: UUID | None = None
    model_name: str | None = Field(
        default=None,
        description="Semantic model name (e.g. 'anomaly_isolation_forest'). "
                    "Distinct from model_version which is a semver tag.",
    )
    # `context_type` is the Sprint 0 alias for `family` — same value,
    # exposed under both names so downstream consumers can read either.
    # We store family canonically; context_type is computed on access.

    # --- existing fields, with Sprint 0 aliases ---
    match_id: UUID
    family: str = Field(alias="context_type")
    context_confidence: float = Field(..., ge=0.0, le=1.0, alias="confidence")
    headline: str = Field(min_length=1, max_length=140, alias="explanation")
    tags: list[str] = Field(default_factory=list, max_length=8)
    top_factors: list[Factor] = Field(
        default_factory=list, max_length=8, alias="contributing_features",
    )
    model_version: str | None = None
    feature_schema_version: int = Field(alias="feature_version")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        alias="created_at",
    )
    # Sprint 0 — surface input-side data confidence alongside model
    # confidence. UI can show e.g. "modelo: 0.82, dados: 0.40" so a
    # confident model with thin data doesn't read as a strong signal.
    data_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Sprint 0.1 — declared sources carried over from the snapshot
    # that produced this output. `source_confidence` is the dict
    # projection (computed); `sources` is canonical.
    sources: list[SourceRef] = Field(default_factory=list)
    # Sprint 0.1 — feature_window_origin carried from the snapshot so
    # consumers can distinguish a `live` inference from a `historical`
    # back-fill output.
    feature_window_origin: FeatureWindowOrigin = Field(
        default=FeatureWindowOrigin.unknown,
    )
    # Sprint 0.1 — final_confidence is the policy-combined score the
    # spec describes (feature_quality × source_conf × data_conf, by
    # default). `context_confidence` is preserved as the raw per-family
    # model signal so consumers can choose which to surface in UI.
    # `None` when the engine couldn't combine (e.g. partial input).
    final_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_confidence(self) -> dict[str, float]:
        return {s.source_id: s.confidence for s in self.sources}

    # ---- validators ----------------------------------------------------

    @field_validator("generated_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("generated_at must be timezone-aware")
        return v

    @field_validator("sport")
    @classmethod
    def _sport_supported(cls, v: str) -> str:
        v = v.lower().strip()
        if v != "football":
            raise ValueError(
                f"sport {v!r} not supported in V1 (only 'football')"
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        """`source_confidence` is a computed_field — emitted on
        `model_dump` for wire convenience. On the way BACK in (cache
        round-trip, copies, deserialisation) the same key would be
        rejected by `extra='forbid'`. Strip it before validation so
        the canonical `sources` list remains the single input form."""
        if isinstance(data, dict) and "source_confidence" in data:
            data = {k: v for k, v in data.items() if k != "source_confidence"}
        return data

    @model_validator(mode="after")
    def _enforce_no_prediction(self) -> "ContextOutput":
        _assert_no_prediction_keys(self.metrics)
        # Also enforce the deny-list against the headline so a
        # well-intentioned operator can't slip a sentence like
        # "Probabilidade home: 72%" into the descriptive output.
        # Case-insensitive substring scan because the headline is free
        # text — the metric scan is exact-key because that's structured.
        lower = self.headline.lower()
        for needle in (
            "win_probability", "probabilidade de vit", "tip do dia",
            "aposta segura", "safe bet", "sure thing",
        ):
            if needle in lower:
                raise ValueError(
                    f"headline contains forbidden phrase {needle!r} "
                    f"(see atlas/inference/output.py deny-list)"
                )
        return self


class MatchContextResponse(BaseModel):
    """Composite response — the four families together."""

    model_config = ConfigDict(extra="forbid")
    match_id: UUID
    feature_schema_version: int
    sport: str = Field(default="football")
    competition_id: UUID | None = None
    data_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Sprint 0.1 — provenance bubbled up from the snapshot.
    sources: list[SourceRef] = Field(default_factory=list)
    feature_window_origin: FeatureWindowOrigin = Field(
        default=FeatureWindowOrigin.unknown,
    )
    anomaly: ContextOutput | None = None
    cluster: ContextOutput | None = None
    density: ContextOutput | None = None
    classifier: ContextOutput | None = None

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and "source_confidence" in data:
            data = {k: v for k, v in data.items() if k != "source_confidence"}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_confidence(self) -> dict[str, float]:
        return {s.source_id: s.confidence for s in self.sources}
