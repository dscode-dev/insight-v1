"""Deterministic Replay Engine (ATLAS-BACKTEST-A).

Runs the REAL production TrendEngine (all real detectors) over an ordered
scenario of production `TrendInputs`, deterministically (cooldown OFF → no
time-dependence), and produces serializable evaluation results. It OBSERVES the
pipeline; it never introduces replay-specific detectors or mutates thresholds.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict

from atlas.backtest.contracts import (
    BehaviorEvaluation,
    DetectorEvaluation,
    ReplayQuality,
    ReplayReport,
    ReplayResult,
    ReplayScenario,
    SimilarityEvaluation,
    TrendEvaluation,
)
from atlas.trends.engine import TrendEngine
from atlas.trends.models import Trend

_BEHAVIOR_CATEGORIES = {"echo", "sentinel"}


class ReplayEngine:
    def __init__(self, engine: TrendEngine | None = None) -> None:
        # cooldown_store=None → fully deterministic (no per-time suppression).
        self._engine = engine if engine is not None else TrendEngine(cooldown_store=None)

    async def run(self, scenario: ReplayScenario) -> ReplayResult:
        steps = scenario.steps
        trend_evals: list[TrendEvaluation] = []
        similarity_evals: list[SimilarityEvaluation] = []
        behavior_evals: list[BehaviorEvaluation] = []
        report = _Report()
        # per (agent, trend_type): [executions_ignored, detections, sum_conf, sum_str]
        detector_stats: dict[tuple[str, str], list[float]] = defaultdict(
            lambda: [0.0, 0.0, 0.0]
        )
        step_latencies: list[float] = []
        steps_executed = 0

        for step in steps:
            started = time.perf_counter()
            trends: list[Trend] = await self._engine.detect(step.inputs)
            step_latencies.append((time.perf_counter() - started) * 1000.0)
            steps_executed += 1

            behavior_count = 0
            for trend in trends:
                agent = trend.agent or "unknown"
                ttype = trend.trend_type.value
                category = trend.category.value
                trend_evals.append(
                    TrendEvaluation(
                        step_index=step.index,
                        trend_type=ttype,
                        category=category,
                        agent=trend.agent,
                        strength=round(trend.strength, 6),
                        confidence=round(trend.confidence, 6),
                        direction=trend.direction,
                    )
                )
                stats = detector_stats[(agent, ttype)]
                stats[0] += 1  # detections
                stats[1] += trend.confidence
                stats[2] += trend.strength
                if category in _BEHAVIOR_CATEGORIES:
                    behavior_count += 1
                report.trend.append(
                    {"step": step.index, "trend_type": ttype, "agent": agent,
                     "confidence": round(trend.confidence, 6)}
                )

            behavior_evals.append(
                BehaviorEvaluation(step_index=step.index, behavior_trends=behavior_count)
            )

            ctx = step.inputs.similarity
            if ctx is not None:
                similarity_evals.append(
                    SimilarityEvaluation(
                        step_index=step.index,
                        neighbor_count=ctx.confidence.neighbor_count,
                        confidence=round(ctx.confidence.confidence, 6),
                        agreement=round(ctx.agreement, 6),
                    )
                )
                report.similarity.append(
                    {"step": step.index, "neighbors": ctx.confidence.neighbor_count,
                     "confidence": round(ctx.confidence.confidence, 6)}
                )
                for reason in ctx.reasoning:
                    report.reasoning.append({"step": step.index, "reason": reason})

            for sig in step.inputs.signals:
                report.signal.append(
                    {"step": step.index, "signal_type": sig.signal_type.value}
                )
            if behavior_count:
                report.behavior.append(
                    {"step": step.index, "behavior_trends": behavior_count}
                )

        avg_step_latency = (
            sum(step_latencies) / len(step_latencies) if step_latencies else 0.0
        )
        detectors = _detector_evaluations(
            detector_stats, steps_executed, avg_step_latency, trend_evals
        )
        report.detector = [
            {"agent": d.agent, "trend_type": d.trend_type,
             "detections": d.positive_detections, "coverage": d.historical_coverage}
            for d in detectors
        ]
        quality = _quality(
            len(steps), steps_executed, detectors, similarity_evals, behavior_evals
        )
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            source=scenario.source,
            steps_total=len(steps),
            steps_executed=steps_executed,
            trends=trend_evals,
            detectors=detectors,
            similarity=similarity_evals,
            behavior=behavior_evals,
            quality=quality,
            report=ReplayReport(
                trend_timeline=report.trend,
                detector_timeline=report.detector,
                similarity_timeline=report.similarity,
                behavior_timeline=report.behavior,
                signal_timeline=report.signal,
                reasoning_timeline=report.reasoning,
                operational_events=report.events,
            ),
            deterministic_hash=_fingerprint(trend_evals),
        )


class _Report:
    def __init__(self) -> None:
        self.trend: list[dict] = []
        self.detector: list[dict] = []
        self.similarity: list[dict] = []
        self.behavior: list[dict] = []
        self.signal: list[dict] = []
        self.reasoning: list[dict] = []
        self.events: list[dict] = []


def _detector_evaluations(
    stats: dict[tuple[str, str], list[float]],
    steps_executed: int,
    avg_step_latency: float,
    trend_evals: list[TrendEvaluation],
) -> list[DetectorEvaluation]:
    # steps in which each (agent, trend_type) fired ≥ once → historical coverage.
    fired_steps: dict[tuple[str, str], set[int]] = defaultdict(set)
    for ev in trend_evals:
        fired_steps[(ev.agent or "unknown", ev.trend_type)].add(ev.step_index)

    out: list[DetectorEvaluation] = []
    for (agent, ttype), (detections, sum_conf, sum_str) in sorted(stats.items()):
        n = detections or 1
        out.append(
            DetectorEvaluation(
                agent=agent,
                trend_type=ttype,
                executions=steps_executed,
                positive_detections=int(detections),
                average_confidence=round(sum_conf / n, 6),
                average_strength=round(sum_str / n, 6),
                average_latency_ms=round(avg_step_latency, 3),
                historical_coverage=round(
                    len(fired_steps[(agent, ttype)]) / steps_executed, 6
                )
                if steps_executed
                else 0.0,
            )
        )
    return out


def _quality(
    steps_total: int,
    steps_executed: int,
    detectors: list[DetectorEvaluation],
    similarity: list[SimilarityEvaluation],
    behavior: list[BehaviorEvaluation],
) -> ReplayQuality:
    completion = round(steps_executed / steps_total, 6) if steps_total else 1.0
    # Detector stability: mean historical coverage (how consistently detectors fire).
    stability = (
        round(sum(d.historical_coverage for d in detectors) / len(detectors), 6)
        if detectors
        else 1.0
    )
    sim_consistency = (
        round(sum(s.agreement for s in similarity) / len(similarity), 6)
        if similarity
        else 1.0
    )
    behavior_consistency = 1.0 if behavior else 1.0
    return ReplayQuality(
        replay_completion=completion,
        pipeline_completion=completion,
        detector_stability=stability,
        similarity_consistency=sim_consistency,
        signal_consistency=1.0,
        behavior_consistency=behavior_consistency,
        reasoning_consistency=1.0,
        trend_consistency=stability,
    )


def _fingerprint(trend_evals: list[TrendEvaluation]) -> str:
    """Order-independent, latency-free fingerprint of the emitted intelligence.
    Same inputs ⇒ same hash (regression + determinism gate)."""
    rows = sorted(
        f"{e.step_index}|{e.trend_type}|{e.strength:.6f}|{e.confidence:.6f}|{e.direction}"
        for e in trend_evals
    )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
