"""Snapshot quarantine — pre-inference gate.

Failure modes this catches (per Sprint 0 spec):

  * Unsupported sport (FeatureSnapshot validator covers this at
    construction, but we keep the check here too so a bypassed
    construction — e.g. raw dict from cache — still hits the gate).
  * Stale timestamp (>1h old by default).
  * data_confidence below the threshold (default 0.20) — i.e. the
    snapshot was almost entirely imputed defaults.
  * schema_version mismatch (the active inference engine targets a
    specific schema; running on a stale schema is silent corruption).
  * Future timestamp (clock drift / replay attack).

Return shape: a decision object with the reason set when quarantined.
The REST layer maps quarantine to HTTP 422 with an explanatory body;
the emitter drops the event and increments a counter.

Why not raise: the caller often wants to LOG the decision (for an ops
dashboard) without blowing up the request. A decision object keeps
that ergonomic.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from atlas.features.snapshot import SUPPORTED_SPORTS, FeatureSnapshot

# Defaults — overridable from the caller. Constants here so tests can
# import + parametrise instead of reaching into magic numbers.
DEFAULT_MIN_DATA_CONFIDENCE: float = 0.20
DEFAULT_MAX_STALENESS: timedelta = timedelta(hours=1)
DEFAULT_MAX_FUTURE_SKEW: timedelta = timedelta(minutes=5)


class QuarantineReason(str, enum.Enum):
    ok = "ok"
    unsupported_sport = "unsupported_sport"
    stale_snapshot = "stale_snapshot"
    future_snapshot = "future_snapshot"
    insufficient_data_confidence = "insufficient_data_confidence"
    schema_version_mismatch = "schema_version_mismatch"


@dataclass(frozen=True)
class QuarantineDecision:
    quarantined: bool
    reason: QuarantineReason
    detail: str = ""

    @classmethod
    def passed(cls) -> "QuarantineDecision":
        return cls(quarantined=False, reason=QuarantineReason.ok)


def quarantine_snapshot(
    snapshot: FeatureSnapshot,
    *,
    active_schema_version: int,
    now: datetime | None = None,
    min_data_confidence: float = DEFAULT_MIN_DATA_CONFIDENCE,
    max_staleness: timedelta = DEFAULT_MAX_STALENESS,
    max_future_skew: timedelta = DEFAULT_MAX_FUTURE_SKEW,
) -> QuarantineDecision:
    """Single entry point. Returns a decision; caller decides how to
    surface it (HTTP status, metric, drop)."""

    if snapshot.sport not in SUPPORTED_SPORTS:
        return QuarantineDecision(
            quarantined=True,
            reason=QuarantineReason.unsupported_sport,
            detail=f"sport={snapshot.sport!r} not in {sorted(SUPPORTED_SPORTS)}",
        )

    if snapshot.schema_version != active_schema_version:
        return QuarantineDecision(
            quarantined=True,
            reason=QuarantineReason.schema_version_mismatch,
            detail=(
                f"snapshot schema={snapshot.schema_version} but engine "
                f"expects {active_schema_version}"
            ),
        )

    ref = now or datetime.now(timezone.utc)
    age = ref - snapshot.ts
    if age > max_staleness:
        return QuarantineDecision(
            quarantined=True,
            reason=QuarantineReason.stale_snapshot,
            detail=f"snapshot is {age.total_seconds():.0f}s old "
                   f"(limit {max_staleness.total_seconds():.0f}s)",
        )
    if -age > max_future_skew:
        # Snapshot timestamp is in the future beyond the skew budget.
        return QuarantineDecision(
            quarantined=True,
            reason=QuarantineReason.future_snapshot,
            detail=f"snapshot is {-age.total_seconds():.0f}s in the future "
                   f"(skew budget {max_future_skew.total_seconds():.0f}s)",
        )

    # Data confidence: if a snapshot was constructed empty or with mostly
    # imputed defaults, its data_confidence will be at or below the
    # threshold. The model would still produce SOME output, but the
    # output would describe defaults instead of reality — exactly the
    # silent-failure mode Sprint 0 says to avoid.
    if snapshot.data_confidence < min_data_confidence:
        return QuarantineDecision(
            quarantined=True,
            reason=QuarantineReason.insufficient_data_confidence,
            detail=(
                f"data_confidence={snapshot.data_confidence:.2f} below "
                f"threshold {min_data_confidence:.2f}"
            ),
        )

    return QuarantineDecision.passed()
