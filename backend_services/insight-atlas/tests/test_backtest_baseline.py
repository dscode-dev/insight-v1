"""Frozen regression baseline: persistence + compatibility gating.

ATLAS_V1_FROZEN.md mandates recording a real-dataset replay as the
frozen baseline that all future replays diff against. That had NO
implementation: the baseline was an in-memory constructor argument,
production never passed one, and nothing could write or read one — so
`RegressionReport` was structurally unable to fire in production.

These cover the recorder/loader and, critically, the refusal to diff
against a baseline recorded under incompatible versions (which would
produce a regression report that looks authoritative and means nothing).
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.backtest.baseline import (
    BaselineIncompatibleError,
    assert_compatible,
    load_baseline,
    save_baseline,
)
from atlas.backtest.contracts import (
    ReplayQuality,
    ReplayReport,
    ReplayResult,
    TrendEvaluation,
)
from atlas.backtest.manifest import build_manifest

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def _result(scenario_id: str = "s1", *, hash_: str = "a" * 64) -> ReplayResult:
    return ReplayResult(
        scenario_id=scenario_id,
        source="competition",
        steps_total=10,
        steps_executed=10,
        trends=[
            TrendEvaluation(
                step_index=0, trend_type="market_shift", category="ninja",
                strength=0.7, confidence=0.8, direction=1, agent="ninja",
            )
        ],
        quality=ReplayQuality(
            replay_completion=1.0, pipeline_completion=1.0, detector_stability=1.0,
            similarity_consistency=1.0, signal_consistency=1.0,
            behavior_consistency=1.0, reasoning_consistency=1.0, trend_consistency=1.0,
        ),
        report=ReplayReport(),
        deterministic_hash=hash_,
    )


def _manifest(**overrides):
    kwargs = dict(
        replay_id="baseline-s1",
        replay_hash="a" * 64,
        dataset="s1",
        execution_timestamp=NOW,
        execution_duration_ms=1234,
    )
    kwargs.update(overrides)
    return build_manifest(**kwargs)


def test_round_trip_preserves_result_and_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "baseline.json"
        original, manifest = _result(), _manifest()
        save_baseline(path, result=original, manifest=manifest)

        loaded_result, loaded_manifest = load_baseline(path)

        assert loaded_result.deterministic_hash == original.deterministic_hash
        assert loaded_result.scenario_id == original.scenario_id
        assert len(loaded_result.trends) == 1
        assert loaded_manifest.feature_schema_version == manifest.feature_schema_version
        assert loaded_manifest.similarity_version == manifest.similarity_version


def test_save_is_atomic_and_leaves_no_temp_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "baseline.json"
        save_baseline(path, result=_result(), manifest=_manifest())
        assert path.exists()
        assert list(Path(tmp).glob("*.tmp")) == []


def test_save_creates_missing_parent_directories():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "nested" / "deeper" / "baseline.json"
        save_baseline(path, result=_result(), manifest=_manifest())
        assert path.exists()


def test_unknown_document_version_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "baseline.json"
        save_baseline(path, result=_result(), manifest=_manifest())
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["document_version"] = "99"
        path.write_text(json.dumps(doc), encoding="utf-8")

        with pytest.raises(BaselineIncompatibleError, match="document_version"):
            load_baseline(path)


# --- compatibility gating ---------------------------------------------------


def test_identical_manifests_are_compatible():
    assert_compatible(_manifest(), _manifest())  # must not raise


def test_similarity_version_mismatch_is_rejected():
    """A v1 baseline must never be diffed against a v2 replay — the two
    describe different embedding schemes entirely."""
    base = _manifest(similarity_version="atlas-memory-embedding-v1")
    current = _manifest(similarity_version="atlas-memory-embedding-v2")
    with pytest.raises(BaselineIncompatibleError, match="similarity_version"):
        assert_compatible(base, current)


def test_detector_inventory_change_is_rejected():
    """Adding or removing a detector changes what CAN be emitted, so
    'no lost detections' would compare different populations."""
    base = _manifest()
    current = _manifest()
    changed = current.model_copy(
        update={"detector_versions": {**current.detector_versions, "NewDetector": "v4"}}
    )
    with pytest.raises(BaselineIncompatibleError, match="detector_versions"):
        assert_compatible(base, changed)


def test_load_with_current_manifest_enforces_compatibility():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "baseline.json"
        save_baseline(
            path,
            result=_result(),
            manifest=_manifest(similarity_version="atlas-memory-embedding-v1"),
        )
        current = _manifest(similarity_version="atlas-memory-embedding-v2")
        with pytest.raises(BaselineIncompatibleError):
            load_baseline(path, current=current)


def test_load_without_current_manifest_skips_the_check():
    """Loading for inspection (no candidate to compare) must still work."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "baseline.json"
        save_baseline(path, result=_result(), manifest=_manifest())
        result, _ = load_baseline(path)
        assert result.scenario_id == "s1"


def test_error_message_names_every_mismatching_field():
    base = _manifest(similarity_version="v1")
    current = _manifest(similarity_version="v2")
    changed = current.model_copy(update={"replay_engine_version": "9.9.9"})
    with pytest.raises(BaselineIncompatibleError) as exc:
        assert_compatible(base, changed)
    message = str(exc.value)
    assert "similarity_version" in message
    assert "replay_engine_version" in message
