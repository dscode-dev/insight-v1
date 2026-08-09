"""Frozen regression baseline — persistence.

`ATLAS_V1_FROZEN.md` mandates:

    Record a real-dataset replay `ReplayManifest` + `ReplayHash` +
    `QualityEvaluation` ... as the frozen baseline; all future replays
    diff against it via the Quality Gate regression report.

That had no implementation. `ReplayService` accepted a `baseline`
constructor argument, but nothing ever wrote one to disk, nothing read
one back, and the production wiring (`atlas/api/app.py`) constructed the
service with no baseline at all — so `RegressionReport` was structurally
unable to fire in production. The Quality Gate could detect a regression
only inside a single process that happened to hold two results in
memory.

This module is the missing half: a baseline is a JSON document on disk
holding the `ReplayResult` plus the `ReplayManifest` that produced it.
The manifest matters as much as the result — a hash is meaningful only
alongside the versions that generated it, so loading refuses a baseline
recorded under incompatible versions rather than silently diffing
against something that isn't comparable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.backtest.contracts import ReplayResult
from atlas.backtest.manifest import ReplayManifest

logger = logging.getLogger(__name__)

BASELINE_DOCUMENT_VERSION = "1"

# Manifest fields that MUST match for a baseline to be comparable to a
# candidate. Everything else (timestamps, durations, artifact paths,
# replay_id) legitimately differs between two runs of the same scenario.
_COMPATIBILITY_FIELDS: tuple[str, ...] = (
    "feature_schema_version",
    "similarity_version",
    "oracle_version",
    "behavior_version",
    "reasoning_version",
    "trend_engine_version",
    "replay_engine_version",
)


class BaselineIncompatibleError(ValueError):
    """Raised when a stored baseline cannot be compared to the current runtime."""


def save_baseline(
    path: str | Path, *, result: ReplayResult, manifest: ReplayManifest
) -> Path:
    """Write the frozen baseline document. Atomic (temp + replace) so a
    crash mid-write can't leave a half-baseline that later loads as if
    it were valid."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "document_version": BASELINE_DOCUMENT_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "manifest": manifest.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    logger.info(
        "atlas_baseline_recorded",
        extra={
            "path": str(target),
            "scenario_id": result.scenario_id,
            "replay_hash": result.deterministic_hash,
        },
    )
    return target


def load_baseline(
    path: str | Path, *, current: ReplayManifest | None = None
) -> tuple[ReplayResult, ReplayManifest]:
    """Read a frozen baseline back.

    When `current` is supplied, the stored manifest is checked against
    it and `BaselineIncompatibleError` is raised on any mismatch of a
    version that affects replay output. Diffing across incompatible
    versions produces a regression report that looks authoritative and
    means nothing — failing loudly is the only safe option.
    """
    document: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    stored_version = str(document.get("document_version", ""))
    if stored_version != BASELINE_DOCUMENT_VERSION:
        raise BaselineIncompatibleError(
            f"baseline document_version {stored_version!r} != "
            f"{BASELINE_DOCUMENT_VERSION!r}"
        )
    manifest = ReplayManifest.model_validate(document["manifest"])
    result = ReplayResult.model_validate(document["result"])
    if current is not None:
        assert_compatible(manifest, current)
    return result, manifest


def assert_compatible(baseline: ReplayManifest, current: ReplayManifest) -> None:
    """Raise unless every output-affecting version matches."""
    mismatches = [
        f"{field}: baseline={getattr(baseline, field)!r} current={getattr(current, field)!r}"
        for field in _COMPATIBILITY_FIELDS
        if getattr(baseline, field) != getattr(current, field)
    ]
    # The detector inventory is part of the contract too: a detector
    # added or removed changes what CAN be emitted, so "no lost
    # detections" would be measuring different populations.
    if baseline.detector_versions != current.detector_versions:
        added = sorted(set(current.detector_versions) - set(baseline.detector_versions))
        removed = sorted(set(baseline.detector_versions) - set(current.detector_versions))
        mismatches.append(f"detector_versions: added={added} removed={removed}")
    if mismatches:
        raise BaselineIncompatibleError(
            "stored baseline is not comparable to the current runtime — "
            "re-record it after reviewing the change: " + "; ".join(mismatches)
        )
