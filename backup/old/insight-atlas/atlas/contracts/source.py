"""Source provenance contracts.

Sprint 0.1 replaces the binary "bot vs real" hint with an explicit
taxonomy. Every piece of data flowing into a FeatureSnapshot or out
in a ContextOutput should declare WHERE it came from so:

  * The confidence policy can weight sources differently.
  * The Sprint 0 quarantine can reject e.g. internal_bot data being
    treated as official fact.
  * The frontend can colour-code provenance ("dado oficial" vs
    "leitura comunitária") without inventing its own taxonomy.

`SourceType` is intentionally additive-only — values are stable. The
Sports Data Hub (Go) mirrors this enum, so removing/renaming any value
would silently break wire compatibility. Always add at the end.

Sprint 0.1.1 hardens `SourceRef` for the upcoming Sports Data Hub:
adds `source_name`, `observed_at`, `adapter_version`, `metadata` so
each event carries full lineage + adapter traceability. New fields
have sensible defaults so existing serialised payloads continue to
deserialise (additive-only contract evolution).
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceType(str, enum.Enum):
    """Categories of data origins.

    Ordered by descending intrinsic trust — a default confidence policy
    can use this as a tie-breaker when two source dicts are otherwise
    equivalent. Numeric values are NOT stored on the wire; only the
    string slugs.
    """

    official_api = "official_api"      # league API direct (e.g. La Liga API)
    commercial_api = "commercial_api"  # licensed provider (api_football, sportmonks)
    official_club = "official_club"    # club's official channel (verified)
    official_league = "official_league"  # league's official channel
    trusted_media = "trusted_media"    # vetted press partner
    internal_bot = "internal_bot"      # our crawler/agent — CANDIDATE only
    community = "community"            # user-generated (signals, posts, sentiment)
    unknown = "unknown"                # ingested before provenance was tagged

    @classmethod
    def candidate_sources(cls) -> set["SourceType"]:
        """Types that must be flagged as candidate, not confirmed fact.

        The quarantine layer uses this to enforce Sprint 0's rule:
        'data from bots treated as official fact' is a violation.
        """
        return {cls.internal_bot, cls.community, cls.unknown}


class SourceRef(BaseModel):
    """One declared source contributing to a feature/snapshot/output.

    Sprint 0.1.1 — extended to support full event lineage. New fields
    over Sprint 0.1:
      * `source_name`     — human-readable label (e.g. "API-Football v3")
      * `observed_at`     — when the producer observed the data
      * `adapter_version` — which adapter binary emitted the ref
      * `metadata`        — opaque bag for adapter-specific provenance

    `confidence` is the trust this run had IN this source — distinct
    from the source's reputation (a long-lived signal). A normally
    trusted commercial_api can land here with confidence 0.4 if its
    payload was suspiciously thin for this particular match.

    Backward compatibility (additive-only):
      * `source_name` defaults to `source_id` when missing — old
        payloads constructed with only the V1 trio still validate;
        the canonical form for new Hub producers IS to send both.
      * `observed_at` defaults to `now(UTC)` so old payloads don't
        crash, but new producers (the Sports Data Hub) MUST set it
        to the actual observation timestamp. A default-filled
        `observed_at` is operationally suspect and downstream
        quarantine policies may flag it in Sprint 1.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    # Defaulted to "" — the after-validator fills it from source_id
    # when the producer didn't set it (V1 payload path).
    source_name: str = Field(default="", max_length=128)
    source_type: SourceType
    confidence: float = Field(ge=0.0, le=1.0)
    # Defaulted to now(UTC) only as a fallback for old payloads. New
    # producers MUST set this to the actual observation time so the
    # quarantine layer can detect stale events upstream.
    observed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    # Which adapter binary produced this ref. Optional because
    # community/user sources don't have an adapter version.
    # Convention: "<adapter_name>@<semver>" e.g. "api_football@1.4.2".
    adapter_version: str | None = Field(default=None, max_length=64)
    # Opaque per-adapter bag. Use for things like:
    #   {"endpoint": "/v3/fixtures/123", "etag": "W/\"abc\"",
    #    "rate_limit_remaining": 42}
    # Wide-open by design — downstream policies may inspect specific
    # keys but the contract makes no schema promise about shape.
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ---- validators ----------------------------------------------------

    @field_validator("observed_at")
    @classmethod
    def _observed_at_tz_aware(cls, v: datetime) -> datetime:
        # Match the existing tz-aware convention used for
        # FeatureSnapshot.ts and ContextOutput.generated_at — keeps
        # every timestamp on the wire fully qualified.
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("observed_at must be timezone-aware")
        return v

    @model_validator(mode="after")
    def _fill_source_name_from_id(self) -> "SourceRef":
        # V1 payloads landed without a separate name. Fill from the
        # id so the wire always carries a non-empty name — keeps the
        # frontend renderer single-path.
        if not self.source_name:
            self.source_name = self.source_id
        return self
