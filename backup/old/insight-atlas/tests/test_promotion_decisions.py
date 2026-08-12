"""Human approval of a Quality Gate replay.

ATLAS_V1_FROZEN.md says "Human approval remains mandatory" for promotion.
These tests pin the rules that make that statement enforceable rather
than aspirational: an approval cannot be recorded without a
justification, without a deciding operator, against a gate that says
Rejected, or against no baseline at all — unless the operator explicitly
and recordably overrides.

Deliberately does NOT import `atlas.api.*`: `atlas/operations.py` pulls
in the POSIX-only `resource` module, which breaks collection of the
whole suite on Windows. The route layer is a thin translation of what is
tested here.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from atlas.backtest.approval import (
    APPROVED,
    REJECTED,
    ApprovalError,
    DecisionRequest,
    PromotionDecisionRepository,
    check,
    summarize,
)
from atlas.backtest.contracts import (
    DetectorReport,
    ExplainabilityReport,
    PromotionReport,
    QualityEvaluation,
    QualityReport,
    RegressionDiff,
    RegressionReport,
)
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base

# -- fixtures ---------------------------------------------------------------- #


@pytest.fixture
async def approvals():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    for tbl in Base.metadata.tables.values():
        tbl.schema = None  # sqlite has no `atlas` schema
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield PromotionDecisionRepository(build_session_factory(engine))
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def _detector(trend_type: str = "momentum") -> DetectorReport:
    return DetectorReport(
        agent="trend_engine",
        trend_type=trend_type,
        executions=100,
        positive_detections=40,
        negative_detections=60,
        suppressed_detections=0,
        average_confidence=0.8,
        average_strength=0.7,
        average_latency_ms=1.0,
        historical_coverage=0.4,
        detector_stability=0.4,
    )


def _quality_report() -> QualityReport:
    return QualityReport(
        has_reference=True,
        detector_agreement=1.0,
        detector_disagreement=0.0,
        similarity_usefulness=0.5,
        reasoning_consistency=1.0,
        trend_stability=0.5,
    )


def _evaluation(
    *,
    replay_hash: str = "hash-candidate",
    verdicts: tuple[str, ...] = ("Approved",),
    with_baseline: bool = True,
    quality_regression: bool = False,
    lost: int = 0,
) -> QualityEvaluation:
    detectors = [_detector(f"trend_{i}") for i in range(len(verdicts))]
    promotions = [
        PromotionReport(
            agent="trend_engine", trend_type=d.trend_type, verdict=v, reasons=["r"]
        )
        for d, v in zip(detectors, verdicts)
    ]
    regression = None
    if with_baseline:
        regression = RegressionReport(
            quality_regression=quality_regression,
            confidence_regression=quality_regression,
            detector_regression=lost > 0,
            trend_regression=lost > 0,
            similarity_regression=False,
            reasoning_regression=False,
            diff=RegressionDiff(
                identical=not quality_regression and lost == 0,
                baseline_hash="hash-baseline",
                candidate_hash=replay_hash,
                lost_detections=[
                    {"step_index": i, "trend_type": f"trend_{i}"} for i in range(lost)
                ],
            ),
        )
    return QualityEvaluation(
        replay_hash=replay_hash,
        detectors=detectors,
        stages=[],
        quality=_quality_report(),
        promotions=promotions,
        explainability=[
            ExplainabilityReport(
                agent="trend_engine", trend_type=d.trend_type, verdict=v, explanation=["r"]
            )
            for d, v in zip(detectors, verdicts)
        ],
        regression=regression,
    )


def _request(**overrides) -> DecisionRequest:
    base = {
        "verdict": APPROVED,
        "reason": "reviewed the diff, no behavioural change",
        "decided_by": "ana",
    }
    base.update(overrides)
    return DecisionRequest(**base)


# -- the gate rules (pure, no database) -------------------------------------- #


class TestCheck:
    def test_accepts_a_clean_approval(self):
        check(_request(), summarize(_evaluation()))

    def test_rejects_an_unknown_verdict(self):
        with pytest.raises(ApprovalError) as exc:
            check(_request(verdict="maybe"), summarize(_evaluation()))
        assert exc.value.code == "invalid_verdict"

    @pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
    def test_requires_a_written_justification(self, reason: str):
        # The gate's own recommendation is not a substitute for the
        # human's reasoning — especially in the override case.
        with pytest.raises(ApprovalError) as exc:
            check(_request(reason=reason), summarize(_evaluation()))
        assert exc.value.code == "reason_required"

    def test_requires_a_deciding_operator(self):
        with pytest.raises(ApprovalError) as exc:
            check(_request(decided_by="  "), summarize(_evaluation()))
        assert exc.value.code == "decider_required"

    def test_blocks_approval_when_the_gate_says_rejected(self):
        evaluation = _evaluation(verdicts=("Approved", "Rejected"), lost=1)
        with pytest.raises(ApprovalError) as exc:
            check(_request(), summarize(evaluation))
        assert exc.value.code == "override_required"

    def test_blocks_approval_on_quality_regression_even_with_no_rejected_verdict(self):
        # A candidate can keep every detection and still weaken all of
        # them — `quality.py::_degraded_types` calls that Warning, not
        # Rejected. It must still not sail through unremarked.
        evaluation = _evaluation(verdicts=("Warning",), quality_regression=True)
        with pytest.raises(ApprovalError) as exc:
            check(_request(), summarize(evaluation))
        assert exc.value.code == "override_required"

    def test_allows_approval_against_the_gate_when_overridden(self):
        evaluation = _evaluation(verdicts=("Rejected",), lost=1)
        check(_request(override_recommendation=True), summarize(evaluation))

    def test_blocks_approval_with_no_baseline(self):
        # "no regression detected" is not a meaningful claim when
        # nothing was compared.
        with pytest.raises(ApprovalError) as exc:
            check(_request(), summarize(_evaluation(with_baseline=False)))
        assert exc.value.code == "baseline_required"

    def test_allows_approval_with_no_baseline_when_acknowledged(self):
        check(
            _request(acknowledge_no_baseline=True),
            summarize(_evaluation(with_baseline=False)),
        )

    def test_rejection_never_needs_an_override_or_acknowledgement(self):
        # Refusing to promote is always safe, so it must never be
        # harder than approving.
        evaluation = _evaluation(
            verdicts=("Rejected",), with_baseline=False, quality_regression=True
        )
        check(_request(verdict=REJECTED), summarize(evaluation))


# -- the snapshot ------------------------------------------------------------ #


class TestSummarize:
    def test_counts_verdicts_and_isolates_the_blocking_ones(self):
        snapshot = summarize(
            _evaluation(verdicts=("Approved", "Warning", "Rejected", "Rejected"), lost=2)
        )
        assert snapshot["verdict_counts"] == {"Approved": 1, "Warning": 1, "Rejected": 2}
        assert len(snapshot["blocking"]) == 2
        assert {b["trend_type"] for b in snapshot["blocking"]} == {"trend_2", "trend_3"}

    def test_records_the_absence_of_a_baseline(self):
        snapshot = summarize(_evaluation(with_baseline=False))
        assert snapshot["has_baseline"] is False
        assert snapshot["baseline_hash"] is None
        assert snapshot["quality_regression"] is False


# -- persistence ------------------------------------------------------------- #


@pytest.mark.asyncio
class TestRepository:
    async def test_records_and_reads_back_a_decision(self, approvals):
        evaluation = _evaluation()
        decision = await approvals.record(
            request=_request(), evaluation=evaluation, execution_id="exec-1"
        )

        assert decision.verdict == APPROVED
        assert decision.decided_by == "ana"
        assert decision.replay_hash == "hash-candidate"
        assert decision.baseline_hash == "hash-baseline"

        stored = await approvals.get_by_hash("hash-candidate")
        assert stored is not None
        assert stored.id == decision.id

    async def test_keys_on_the_replay_hash_not_the_execution_id(self, approvals):
        # ReplayService holds executions in memory, so an execution id
        # stops resolving after a restart while the hash identifies the
        # evaluated behaviour forever.
        await approvals.record(
            request=_request(), evaluation=_evaluation(), execution_id="exec-1"
        )
        found = await approvals.get_by_hash("hash-candidate")
        assert found is not None and found.execution_id == "exec-1"

    async def test_refuses_a_second_decision_on_the_same_replay_hash(self, approvals):
        await approvals.record(
            request=_request(), evaluation=_evaluation(), execution_id="exec-1"
        )
        with pytest.raises(ApprovalError) as exc:
            await approvals.record(
                request=_request(verdict=REJECTED, decided_by="bruno"),
                evaluation=_evaluation(),
                execution_id="exec-2",
            )
        # Same code, same data → same hash. A contradicting second
        # decision must surface, not silently overwrite the first.
        assert exc.value.code == "decision_exists"
        assert "ana" in str(exc.value)

    async def test_flags_an_override_in_its_own_column(self, approvals):
        decision = await approvals.record(
            request=_request(override_recommendation=True),
            evaluation=_evaluation(verdicts=("Rejected",), lost=1),
            execution_id="exec-1",
        )
        # An auditor looking for "who shipped against the gate" must be
        # able to filter on a column, not parse a JSON blob.
        assert decision.overrode_recommendation is True
        assert decision.without_baseline is False

    async def test_flags_a_baseline_less_approval(self, approvals):
        decision = await approvals.record(
            request=_request(acknowledge_no_baseline=True),
            evaluation=_evaluation(with_baseline=False),
            execution_id="exec-1",
        )
        assert decision.without_baseline is True
        assert decision.baseline_hash is None

    async def test_a_rejection_is_not_marked_as_an_override(self, approvals):
        decision = await approvals.record(
            request=_request(verdict=REJECTED),
            evaluation=_evaluation(verdicts=("Rejected",), lost=1),
            execution_id="exec-1",
        )
        # Agreeing WITH the gate is the opposite of overriding it.
        assert decision.overrode_recommendation is False

    async def test_freezes_the_recommendation_the_operator_actually_saw(self, approvals):
        decision = await approvals.record(
            request=_request(override_recommendation=True),
            evaluation=_evaluation(verdicts=("Approved", "Rejected"), lost=1),
            execution_id="exec-1",
        )
        # The evaluation lives in memory only; without this snapshot the
        # justification for the decision becomes uncheckable after a
        # restart.
        assert decision.recommendation["verdict_counts"]["Rejected"] == 1
        assert decision.recommendation["detections_lost"] == 1

    async def test_history_is_newest_first(self, approvals):
        for i in range(3):
            await approvals.record(
                request=_request(reason=f"reason {i}"),
                evaluation=_evaluation(replay_hash=f"hash-{i}"),
                execution_id=f"exec-{i}",
            )
        history = await approvals.history(limit=10)
        assert [d.replay_hash for d in history] == ["hash-2", "hash-1", "hash-0"]

    async def test_a_refused_decision_writes_nothing(self, approvals):
        with pytest.raises(ApprovalError):
            await approvals.record(
                request=_request(),  # no override, gate says Rejected
                evaluation=_evaluation(verdicts=("Rejected",), lost=1),
                execution_id="exec-1",
            )
        assert await approvals.get_by_hash("hash-candidate") is None
