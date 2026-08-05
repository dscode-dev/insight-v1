"""Quality Gate promotion verdicts must not contradict the regression report.

Round 6 finding: `_promotions` gated ONLY on `diff.lost_detections`, so a
candidate that kept every detection but weakened all of them was stamped
"Approved — ... no regression" while the very same RegressionReport had
`confidence_regression=True`. The verdict is what an operator reads, and
it disagreed with the report next to it.

Separately, `reasoning_reg` was computed and then never folded into the
aggregate `quality_regression` flag.

This matters right now: the Round 4 changes to the frozen core altered
confidence/strength in several engines, and this gate is what validates
whether those are safe to promote.
"""

from __future__ import annotations

from atlas.backtest.contracts import DetectorReport, RegressionReport
from atlas.backtest.quality import _degraded_types, _lost_types, _promotions
from atlas.backtest.regression import RegressionDiff


def _diff(*, lost=None, confidence_changes=None, strength_changes=None) -> RegressionDiff:
    return RegressionDiff(
        identical=not (lost or confidence_changes or strength_changes),
        baseline_hash="a" * 64,
        candidate_hash="b" * 64,
        new_detections=[],
        lost_detections=lost or [],
        confidence_changes=confidence_changes or [],
        strength_changes=strength_changes or [],
        trend_changes=[],
    )


def _regression(diff: RegressionDiff) -> RegressionReport:
    downward = any(c["to"] < c["from"] for c in diff.confidence_changes)
    return RegressionReport(
        quality_regression=bool(diff.lost_detections) or downward,
        confidence_regression=downward,
        detector_regression=bool(diff.lost_detections),
        trend_regression=bool(diff.lost_detections),
        similarity_regression=False,
        reasoning_regression=False,
        diff=diff,
    )


def _detector(trend_type: str = "market_shift") -> DetectorReport:
    return DetectorReport(
        agent="ninja",
        trend_type=trend_type,
        executions=10,
        positive_detections=8,
        average_confidence=0.8,
        average_strength=0.7,
        average_latency_ms=1.0,
        historical_coverage=0.8,
        detector_stability=0.9,
        negative_detections=2,
        suppressed_detections=0,
    )


# --- the helpers ------------------------------------------------------------


def test_degraded_types_detects_confidence_drop():
    diff = _diff(confidence_changes=[
        {"step": 0, "trend_type": "market_shift", "from": 0.9, "to": 0.5},
    ])
    assert _degraded_types(_regression(diff)) == {"market_shift"}


def test_degraded_types_ignores_improvements():
    diff = _diff(confidence_changes=[
        {"step": 0, "trend_type": "market_shift", "from": 0.5, "to": 0.9},
    ])
    assert _degraded_types(_regression(diff)) == set()


def test_degraded_types_detects_strength_drop():
    diff = _diff(strength_changes=[
        {"step": 0, "trend_type": "market_shift", "from": 0.8, "to": 0.4},
    ])
    assert _degraded_types(_regression(diff)) == {"market_shift"}


def test_degraded_types_empty_without_regression_report():
    assert _degraded_types(None) == set()


# --- the verdict ------------------------------------------------------------


def test_confidence_drop_is_not_reported_as_no_regression():
    """The core regression: a weakened-but-retained detection must never
    be Approved with the reason 'no regression'."""
    diff = _diff(confidence_changes=[
        {"step": 0, "trend_type": "market_shift", "from": 0.9, "to": 0.4},
    ])
    promotions, _ = _promotions([_detector()], _regression(diff))

    verdict = promotions[0]
    assert verdict.verdict != "Approved"
    joined = " ".join(verdict.reasons)
    assert "no regression" not in joined
    assert "regression" in joined


def test_lost_detection_still_rejects():
    diff = _diff(lost=[
        {"step": 0, "trend_type": "market_shift", "confidence": 0.9},
    ])
    promotions, _ = _promotions([_detector()], _regression(diff))
    assert promotions[0].verdict == "Rejected"


def test_clean_candidate_is_still_approved():
    """Guard against over-correction: a genuinely clean run must still
    pass."""
    promotions, _ = _promotions([_detector()], _regression(_diff()))
    assert promotions[0].verdict == "Approved"


def test_improvement_is_still_approved():
    diff = _diff(confidence_changes=[
        {"step": 0, "trend_type": "market_shift", "from": 0.4, "to": 0.9},
    ])
    promotions, _ = _promotions([_detector()], _regression(diff))
    assert promotions[0].verdict == "Approved"


def test_degradation_of_a_different_detector_does_not_taint_this_one():
    diff = _diff(confidence_changes=[
        {"step": 0, "trend_type": "pressure_building", "from": 0.9, "to": 0.4},
    ])
    promotions, _ = _promotions([_detector("market_shift")], _regression(diff))
    assert promotions[0].verdict == "Approved"


def test_lost_types_and_degraded_types_are_disjoint_concerns():
    diff = _diff(
        lost=[{"step": 0, "trend_type": "a", "confidence": 0.9}],
        confidence_changes=[{"step": 1, "trend_type": "b", "from": 0.9, "to": 0.4}],
    )
    reg = _regression(diff)
    assert _lost_types(reg) == {"a"}
    assert _degraded_types(reg) == {"b"}
