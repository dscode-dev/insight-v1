"""Validation layer — quarantines snapshots that don't meet the
minimum data-quality bar before they reach a model.

Sprint 0 mandate:
    "The ML pipeline must reject or quarantine:
       * data without source metadata
       * data without timestamp
       * data without confidence
       * stale data
       * malformed odds
       * unknown competition
       * unsupported sports
       * data from bots treated as official fact
       * contradictory data without conflict resolution"

This module covers the subset that's checkable from a `FeatureSnapshot`
alone. Source-metadata / bot-vs-real distinctions need the upstream
Sports Data Hub (out of scope this sprint) — they're flagged in the
Sprint 1 readiness checklist.
"""

from atlas.validation.quarantine import (
    QuarantineDecision,
    QuarantineReason,
    quarantine_snapshot,
)

__all__ = ["QuarantineDecision", "QuarantineReason", "quarantine_snapshot"]
