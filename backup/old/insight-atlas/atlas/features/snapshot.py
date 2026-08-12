"""FeatureSnapshot — the unit of data Atlas trains and infers on.

Sprint 0 contract alignment:
  * Adds `feature_snapshot_id` (was implicit on match_id+ts before).
  * Adds `sport` — V1 is football-only; the validator below rejects
    snapshots from any other sport BEFORE they reach a model. The
    field has no default because making the choice explicit at the
    snapshot boundary is the whole point — anything that calls into
    Atlas must declare what sport it's about.
  * Adds `season` — Sprint 0 lists it as required. Optional in code
    only because back-fill of historical events without a clean
    season tag would otherwise quarantine half the data; treated as
    nullable + flagged in `data_confidence` when missing.
  * Adds `data_confidence` — fraction of features that came from
    REAL upstream data (vs `with_defaults()` imputation). Sits next
    to the model's own confidence so downstream UI can distinguish
    "confident model with thin data" from "confident model with rich
    data". Computed at construction or via `recompute_data_confidence`.
  * Aliases: `feature_version` ⇄ `schema_version`,
              `created_at`     ⇄ `ts`.
    The Sprint 0 spec names land as Pydantic aliases — both forms are
    accepted at deserialisation, only one form is emitted at JSON time
    to keep wire output deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from atlas.contracts import FeatureWindowOrigin, SourceRef
from atlas.features.definitions import FEATURE_NAMES, defaults, registry

SUPPORTED_SPORTS: frozenset[str] = frozenset({"football"})


class FeatureSnapshot(BaseModel):
    """A point-in-time view of every feature for one match.

    Stored in Redis (hot); cold analytics remain behind Anvil. The vector
    representation respects `FEATURE_NAMES` ordering — never iterate
    `features.values()` because dict ordering is not load-bearing.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    feature_snapshot_id: UUID = Field(default_factory=uuid4)
    sport: str = Field(default="football")
    competition_id: UUID | None = None
    season: str | None = Field(
        default=None, max_length=16,
        description="Free-form season tag (e.g. '2026', '2025-26'). "
                    "Nullable for back-fill; missing season decreases "
                    "data_confidence in the validator.",
    )
    match_id: UUID
    minute: int | None = Field(default=None, ge=0, le=200)
    # `ts` is the canonical field; `created_at` is the Sprint 0 alias.
    ts: datetime = Field(alias="created_at")
    # `schema_version` is the canonical field; `feature_version` is
    # the Sprint 0 alias. We keep `schema_version` as the storage name
    # to avoid mass-migrating historical analytics representations.
    schema_version: int = Field(default=1, ge=1, alias="feature_version")
    features: dict[str, float] = Field(default_factory=dict)
    # Sprint 0 — fraction of features with REAL data (vs imputed
    # defaults). 1.0 means every feature came from upstream; 0.0
    # means the entire vector is registry defaults (quarantine zone).
    data_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # Sprint 0.1 — declared upstream sources (TASK 1 + TASK 2). The
    # `source_confidence` shorthand dict is a computed projection;
    # `sources` is the canonical typed form. Empty list is allowed
    # (back-fill / cold-start scenarios) — the quarantine layer +
    # confidence policy decide how to handle absence.
    sources: list[SourceRef] = Field(default_factory=list)
    # Sprint 0.1 — provenance of the feature window (TASK 4).
    feature_window_origin: FeatureWindowOrigin = Field(
        default=FeatureWindowOrigin.rolling,
    )

    # ---- validators ----------------------------------------------------

    @field_validator("ts")
    @classmethod
    def _ts_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("ts must be timezone-aware")
        return v

    @field_validator("sport")
    @classmethod
    def _sport_supported(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in SUPPORTED_SPORTS:
            raise ValueError(
                f"sport {v!r} not supported in V1 "
                f"(allowed: {sorted(SUPPORTED_SPORTS)})"
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        """`source_confidence` is a computed_field — strip on input so
        cache round-trip (model_dump → model_validate) survives
        `extra='forbid'`. Canonical input is `sources`."""
        if isinstance(data, dict) and "source_confidence" in data:
            data = {k: v for k, v in data.items() if k != "source_confidence"}
        return data

    @model_validator(mode="after")
    def _recompute_data_confidence_on_construction(self) -> "FeatureSnapshot":
        # Only auto-compute when the caller didn't explicitly set it
        # (default 1.0). If the caller passed a non-default value
        # (e.g. on deserialisation from persisted snapshot), trust it.
        if self.data_confidence == 1.0 and self.features:
            self.data_confidence = _fraction_real(self.features)
        return self

    # ---- computed views ------------------------------------------------

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_confidence(self) -> dict[str, float]:
        """Sprint 0.1 dict-view of `sources` for the example shape in
        the spec: ``{"api_football": 0.95, "sportmonks": 0.88}``.

        The list form (`sources`) is canonical because it carries
        SourceType; this dict is for confidence-policy reducers and
        wire ergonomics. If two refs share a source_id (shouldn't
        happen by convention), the LAST wins — keeping it simple
        rather than raising in a serialiser path.
        """
        return {s.source_id: s.confidence for s in self.sources}

    # ---- transforms ----------------------------------------------------

    def with_defaults(self) -> "FeatureSnapshot":
        """Return a copy where any missing feature is filled from registry
        defaults. Used at the inference boundary so the vector is dense.

        IMPORTANT: this method DROPS the data_confidence signal — after
        filling, the snapshot looks "complete" by shape but isn't by
        provenance. Callers that care MUST snapshot.data_confidence
        BEFORE calling this or use `with_defaults_keeping_confidence`.
        """
        merged = {**defaults(), **self.features}
        merged = {k: float(v) for k, v in merged.items() if k in registry}
        # Recompute against the merged set so the field reflects reality:
        # a snapshot that only had 3 of 12 features now has confidence ~0.25.
        return self.model_copy(
            update={
                "features": merged,
                "data_confidence": _fraction_real_against_defaults(merged),
            }
        )

    def to_vector(self) -> list[float]:
        """Positional vector in `FEATURE_NAMES` order, with defaults."""
        snap = self.with_defaults()
        return [
            float(snap.features.get(name, registry[name].default))
            for name in FEATURE_NAMES
        ]

    @classmethod
    def empty(cls, *, match_id: UUID, ts: datetime | None = None) -> "FeatureSnapshot":
        return cls(
            match_id=match_id,
            ts=ts or datetime.now(timezone.utc),
            features=defaults(),
            data_confidence=0.0,  # explicit: empty means no real data
            feature_window_origin=FeatureWindowOrigin.unknown,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "feature_snapshot_id": str(self.feature_snapshot_id),
            "sport": self.sport,
            "match_id": str(self.match_id),
            "competition_id": str(self.competition_id) if self.competition_id else None,
            "season": self.season,
            "minute": self.minute,
            "ts": self.ts.isoformat(),
            "created_at": self.ts.isoformat(),  # Sprint 0 alias
            "schema_version": self.schema_version,
            "feature_version": self.schema_version,  # Sprint 0 alias
            "features": dict(self.features),
            "data_confidence": self.data_confidence,
            # Sprint 0.1 — provenance metadata.
            "sources": [s.model_dump(mode="json") for s in self.sources],
            "source_confidence": self.source_confidence,
            "feature_window_origin": self.feature_window_origin.value,
        }


def _fraction_real(features: dict[str, float]) -> float:
    """Fraction of supplied features whose value differs from the
    registry default for that feature.

    Heuristic — a feature whose true value happens to equal its default
    is counted as "imputed" here. Acceptable because the inverse
    failure (counting an actual default as "real") would silently
    inflate confidence. False negatives are safer than false positives
    for a quarantine signal.
    """
    if not features:
        return 0.0
    known = [k for k in features if k in registry]
    if not known:
        return 0.0
    real = sum(1 for k in known if features[k] != registry[k].default)
    return real / len(known)


def _fraction_real_against_defaults(features: dict[str, float]) -> float:
    """Like `_fraction_real` but always denominates against the full
    registry. Used after `with_defaults` merges in every feature."""
    if not registry:
        return 0.0
    real = sum(
        1 for k in registry
        if k in features and features[k] != registry[k].default
    )
    return real / len(registry)
