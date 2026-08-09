"""Deterministic Quality Gate (ATLAS-BACKTEST-B, Stages 1-6).

Evaluates a ReplayResult without touching production intelligence: detector
reports, per-stage pipeline evaluation, reproducible quality metrics, a
regression report vs a baseline, promotion recommendations (Approved / Warning /
Rejected — recommend only), and deterministic template explanations. No ML, no
threshold recalibration, no AI-written text, no estimated values.
"""

from __future__ import annotations

from atlas.backtest.contracts import (
    DetectorReport,
    ExplainabilityReport,
    PromotionReport,
    QualityEvaluation,
    QualityReport,
    RegressionReport,
    ReplayResult,
    StageEvaluation,
)
from atlas.backtest.regression import diff_replays

# Gate decision thresholds — these govern the RECOMMENDATION only; they never
# touch a detector's own thresholds (which are forbidden to change).
_MIN_COVERAGE = 0.02
_MIN_STABILITY = 0.30


def evaluate(result: ReplayResult, *, baseline: ReplayResult | None = None) -> QualityEvaluation:
    detectors = _detector_reports(result)
    stages = _stage_evaluations(result)
    quality = _quality_report(result, baseline)
    regression = _regression_report(result, baseline) if baseline is not None else None
    promotions, explain = _promotions(detectors, regression)
    return QualityEvaluation(
        replay_hash=result.deterministic_hash,
        detectors=detectors,
        stages=stages,
        quality=quality,
        promotions=promotions,
        explainability=explain,
        regression=regression,
    )


# -- Stage 1: detector reports (generic) ------------------------------------- #
def _detector_reports(result: ReplayResult) -> list[DetectorReport]:
    out: list[DetectorReport] = []
    for d in result.detectors:
        negative = max(0, d.executions - d.positive_detections)
        out.append(
            DetectorReport(
                agent=d.agent,
                trend_type=d.trend_type,
                executions=d.executions,
                positive_detections=d.positive_detections,
                negative_detections=negative,
                suppressed_detections=0,  # cooldown OFF in replay → deterministic
                average_confidence=d.average_confidence,
                average_strength=d.average_strength,
                average_latency_ms=d.average_latency_ms,
                historical_coverage=d.historical_coverage,
                detector_stability=d.historical_coverage,
            )
        )
    return out


# -- Stage 2: per-stage pipeline evaluation (generic counts) ----------------- #
def _stage_evaluations(result: ReplayResult) -> list[StageEvaluation]:
    steps = result.steps_executed
    signal_steps = len({e["step"] for e in result.report.signal_timeline})
    reasoning_steps = len({e["step"] for e in result.report.reasoning_timeline})
    behavior_dets = sum(b.behavior_trends for b in result.behavior)
    oracle_dets = sum(
        1 for t in result.trends if t.trend_type.startswith("historical_")
    )
    return [
        StageEvaluation(stage="explorer", executions=steps, inputs_present=steps, detections=steps),
        StageEvaluation(stage="signals", executions=steps, inputs_present=signal_steps,
                        detections=len(result.report.signal_timeline)),
        StageEvaluation(stage="behavior", executions=steps, inputs_present=len(result.behavior),
                        detections=behavior_dets),
        StageEvaluation(stage="similarity", executions=steps, inputs_present=len(result.similarity),
                        detections=len(result.similarity)),
        StageEvaluation(stage="oracle", executions=steps, inputs_present=len(result.similarity),
                        detections=oracle_dets),
        StageEvaluation(stage="reasoning", executions=steps, inputs_present=reasoning_steps,
                        detections=len(result.report.reasoning_timeline)),
        StageEvaluation(stage="trend_engine", executions=steps, inputs_present=steps,
                        detections=len(result.trends)),
    ]


# -- Stage 3: quality metrics ------------------------------------------------ #
def _detection_set(result: ReplayResult) -> set[tuple[int, str]]:
    return {(t.step_index, t.trend_type) for t in result.trends}


def _quality_report(result: ReplayResult, baseline: ReplayResult | None) -> QualityReport:
    precision = recall = f1 = None
    fp = fn = None
    if baseline is not None:
        cand, base = _detection_set(result), _detection_set(baseline)
        tp = len(cand & base)
        fp = len(cand - base)
        fn = len(base - cand)
        precision = round(tp / (tp + fp), 6) if (tp + fp) else (1.0 if fn == 0 else 0.0)
        recall = round(tp / (tp + fn), 6) if (tp + fn) else (1.0 if fp == 0 else 0.0)
        f1 = round(2 * precision * recall / (precision + recall), 6) if (precision + recall) else 0.0

    # Detector agreement: over steps with any detection, fraction with ≥2 agents.
    by_step: dict[int, set[str]] = {}
    for t in result.trends:
        by_step.setdefault(t.step_index, set()).add(t.agent or "unknown")
    steps_with_det = len(by_step)
    multi = sum(1 for agents in by_step.values() if len(agents) >= 2)
    agreement = round(multi / steps_with_det, 6) if steps_with_det else 1.0

    sim_usefulness = (
        round(sum(s.confidence for s in result.similarity) / len(result.similarity), 6)
        if result.similarity
        else 0.0
    )
    reasoning_consistency = (
        round(len({e["step"] for e in result.report.reasoning_timeline})
              / len(result.similarity), 6)
        if result.similarity
        else 1.0
    )
    trend_stability = (
        round(sum(d.historical_coverage for d in result.detectors) / len(result.detectors), 6)
        if result.detectors
        else 1.0
    )
    return QualityReport(
        has_reference=baseline is not None,
        precision=precision, recall=recall, f1_score=f1,
        false_positives=fp, false_negatives=fn,
        detector_agreement=agreement,
        detector_disagreement=round(1.0 - agreement, 6),
        similarity_usefulness=sim_usefulness,
        reasoning_consistency=min(1.0, reasoning_consistency),
        trend_stability=trend_stability,
    )


# -- Stage 4: regression gate ------------------------------------------------ #
def _regression_report(result: ReplayResult, baseline: ReplayResult) -> RegressionReport:
    diff = diff_replays(baseline, result)
    downward = any(c["to"] < c["from"] for c in diff.confidence_changes)
    base_q = _quality_report(baseline, None)
    cand_q = _quality_report(result, None)
    similarity_reg = cand_q.similarity_usefulness < base_q.similarity_usefulness - 1e-9
    reasoning_reg = cand_q.reasoning_consistency < base_q.reasoning_consistency - 1e-9
    detector_reg = bool(diff.lost_detections)
    return RegressionReport(
        # `reasoning_reg` was computed and then dropped on the floor —
        # it never contributed to the aggregate flag, so a reasoning
        # regression was detected and then silently ignored by every
        # consumer that reads `quality_regression`.
        quality_regression=(
            detector_reg or downward or similarity_reg or reasoning_reg
        ),
        confidence_regression=downward,
        detector_regression=detector_reg,
        trend_regression=detector_reg,
        similarity_regression=similarity_reg,
        reasoning_regression=reasoning_reg,
        diff=diff,
    )


# -- Stage 5-6: promotion + explainability ----------------------------------- #
def _lost_types(regression: RegressionReport | None) -> set[str]:
    if regression is None:
        return set()
    return {row["trend_type"] for row in regression.diff.lost_detections}


def _degraded_types(regression: RegressionReport | None) -> set[str]:
    """Trend types whose confidence or strength DROPPED vs the baseline
    without the detection being lost outright.

    Promotion used to gate on `_lost_types` alone, so a candidate that
    kept every detection but degraded all of them was still stamped
    "Approved — ... no regression" while `RegressionReport
    .confidence_regression` was True. The report and the verdict
    contradicted each other, and the verdict is what an operator reads.
    """
    if regression is None:
        return set()
    degraded: set[str] = set()
    for row in (*regression.diff.confidence_changes, *regression.diff.strength_changes):
        if row["to"] < row["from"]:
            degraded.add(row["trend_type"])
    return degraded


def _promotions(
    detectors: list[DetectorReport], regression: RegressionReport | None
) -> tuple[list[PromotionReport], list[ExplainabilityReport]]:
    lost = _lost_types(regression)
    degraded = _degraded_types(regression)
    promotions: list[PromotionReport] = []
    explain: list[ExplainabilityReport] = []
    for d in detectors:
        reasons: list[str] = []
        if d.trend_type in lost:
            verdict = "Rejected"
            reasons.append("regression: detections lost vs baseline")
        elif d.trend_type in degraded:
            # Kept the detection but weakened it — not a rejection, but
            # it must never be reported as "no regression".
            verdict = "Warning"
            reasons.append(
                "regression: confidence/strength decreased vs baseline "
                "(detection retained)"
            )
        elif d.positive_detections == 0 or d.historical_coverage < _MIN_COVERAGE:
            verdict = "Warning"
            reasons.append(
                f"low historical coverage ({d.historical_coverage:.3f}); insufficient evidence"
            )
        elif d.detector_stability < _MIN_STABILITY:
            verdict = "Warning"
            reasons.append(f"confidence/coverage instability (stability {d.detector_stability:.3f})")
        else:
            verdict = "Approved"
            reasons.append(
                f"stable coverage {d.historical_coverage:.3f}, "
                f"avg confidence {d.average_confidence:.3f}, no regression"
            )
        promotions.append(
            PromotionReport(agent=d.agent, trend_type=d.trend_type, verdict=verdict, reasons=reasons)
        )
        explain.append(
            ExplainabilityReport(
                agent=d.agent, trend_type=d.trend_type, verdict=verdict, explanation=reasons
            )
        )
    return promotions, explain
