"""Human approval of a Quality Gate replay.

ATLAS_V1_FROZEN.md: "Every new detector/heuristic MUST pass the Quality
Gate (regression + promotion) against the frozen baseline before
promotion. Human approval remains mandatory."

Before this module the second sentence had no implementation at all.
`quality.py` computed per-detector verdicts, `/backtests/{id}/quality`
returned them, and nothing consumed or recorded them. This module is
where a person's decision on a replay becomes a durable, auditable fact.

Two rules are enforced here rather than left to the caller, because
they are the whole point of the gate:

  * approving a replay whose gate recommendation contains a `Rejected`
    verdict, or which reports `quality_regression`, requires an
    explicit override flag — the operator must state that they are
    going against the gate, and it is recorded as such;
  * approving a replay that had NO baseline to diff against requires an
    explicit acknowledgement — "no regression detected" is not a
    meaningful statement when nothing was compared, and that distinction
    disappears entirely once it is only a row in a table.

Rejections need neither flag: refusing to promote is always safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from atlas.backtest.contracts import QualityEvaluation
from atlas.registry.models import PromotionDecisionRow

logger = logging.getLogger(__name__)

APPROVED = "approved"
REJECTED = "rejected"
_VERDICTS = (APPROVED, REJECTED)

# The gate verdict that blocks an approval unless explicitly overridden.
_BLOCKING_VERDICT = "Rejected"


class ApprovalError(Exception):
    """A decision was refused. Carries a stable machine-readable code so
    the API layer can map it to a status without string-matching."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DecisionRequest:
    verdict: str
    reason: str
    decided_by: str
    override_recommendation: bool = False
    acknowledge_no_baseline: bool = False


@dataclass(frozen=True)
class Decision:
    """Read model — what an operator or auditor sees."""

    id: UUID
    replay_hash: str
    execution_id: str
    baseline_hash: str | None
    verdict: str
    decided_by: str
    reason: str
    overrode_recommendation: bool
    without_baseline: bool
    quality_regression: bool
    recommendation: dict[str, Any]
    decided_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "replay_hash": self.replay_hash,
            "execution_id": self.execution_id,
            "baseline_hash": self.baseline_hash,
            "verdict": self.verdict,
            "decided_by": self.decided_by,
            "reason": self.reason,
            "overrode_recommendation": self.overrode_recommendation,
            "without_baseline": self.without_baseline,
            "quality_regression": self.quality_regression,
            "recommendation": self.recommendation,
            "decided_at": self.decided_at.isoformat(),
        }


def summarize(evaluation: QualityEvaluation) -> dict[str, Any]:
    """Snapshot of what the gate recommended, frozen into the decision.

    Stored rather than re-derived because `ReplayService` holds
    evaluations in memory only — after a restart the recommendation the
    operator actually saw would otherwise be unrecoverable, leaving a
    decision whose justification cannot be checked.
    """
    counts: dict[str, int] = {}
    blocking: list[dict[str, Any]] = []
    for promo in evaluation.promotions:
        counts[promo.verdict] = counts.get(promo.verdict, 0) + 1
        if promo.verdict == _BLOCKING_VERDICT:
            blocking.append(
                {
                    "agent": promo.agent,
                    "trend_type": promo.trend_type,
                    "reasons": list(promo.reasons),
                }
            )
    regression = evaluation.regression
    return {
        "replay_hash": evaluation.replay_hash,
        "verdict_counts": counts,
        "blocking": blocking,
        "has_baseline": regression is not None,
        "baseline_hash": regression.diff.baseline_hash if regression else None,
        "quality_regression": bool(regression.quality_regression) if regression else False,
        "regression_flags": (
            {
                "confidence": regression.confidence_regression,
                "detector": regression.detector_regression,
                "trend": regression.trend_regression,
                "similarity": regression.similarity_regression,
                "reasoning": regression.reasoning_regression,
            }
            if regression
            else {}
        ),
        "detections_lost": len(regression.diff.lost_detections) if regression else 0,
        "detections_new": len(regression.diff.new_detections) if regression else 0,
    }


def check(request: DecisionRequest, snapshot: dict[str, Any]) -> None:
    """Raise `ApprovalError` if `request` may not be recorded.

    Pure and separately testable: the gate's rules should not require a
    database to exercise.
    """
    if request.verdict not in _VERDICTS:
        raise ApprovalError("invalid_verdict", f"verdict must be one of {_VERDICTS}")
    if not request.reason.strip():
        raise ApprovalError("reason_required", "a written justification is required")
    if not request.decided_by.strip():
        raise ApprovalError("decider_required", "the deciding operator is unknown")

    if request.verdict != APPROVED:
        # Refusing to promote is always allowed.
        return

    if not snapshot.get("has_baseline", False) and not request.acknowledge_no_baseline:
        raise ApprovalError(
            "baseline_required",
            "this replay was not diffed against a frozen baseline; approving it "
            "means accepting an unverified regression profile — set "
            "acknowledge_no_baseline to record that explicitly",
        )

    blocking = snapshot.get("blocking") or []
    regressed = bool(snapshot.get("quality_regression", False))
    if (blocking or regressed) and not request.override_recommendation:
        raise ApprovalError(
            "override_required",
            "the Quality Gate did not clear this replay "
            f"({len(blocking)} rejected detector(s), "
            f"quality_regression={regressed}) — set override_recommendation to "
            "approve against the gate's recommendation",
        )


class PromotionDecisionRepository:
    """Durable store for approve/reject decisions."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def record(
        self,
        *,
        request: DecisionRequest,
        evaluation: QualityEvaluation,
        execution_id: str,
    ) -> Decision:
        snapshot = summarize(evaluation)
        check(request, snapshot)

        blocking = snapshot.get("blocking") or []
        regressed = bool(snapshot.get("quality_regression", False))
        row = PromotionDecisionRow(
            id=uuid4(),
            replay_hash=evaluation.replay_hash,
            execution_id=execution_id,
            baseline_hash=snapshot.get("baseline_hash"),
            verdict=request.verdict,
            decided_by=request.decided_by.strip(),
            reason=request.reason.strip(),
            overrode_recommendation=(
                request.verdict == APPROVED and bool(blocking or regressed)
            ),
            without_baseline=not snapshot.get("has_baseline", False),
            quality_regression=regressed,
            recommendation=snapshot,
            decided_at=datetime.now(timezone.utc),
        )
        async with self._sf() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                # The unique index on replay_hash fired: a decision on
                # this exact behaviour already exists. Surface it rather
                # than overwriting — a second, differing decision on the
                # same fingerprint is exactly the conflict an auditor
                # needs to see.
                await session.rollback()
                existing = await self.get_by_hash(evaluation.replay_hash)
                raise ApprovalError(
                    "decision_exists",
                    "a decision was already recorded for this replay hash"
                    + (f" by {existing.decided_by}" if existing else ""),
                ) from None
        logger.info(
            "promotion_decision_recorded",
            extra={
                "replay_hash": row.replay_hash,
                "verdict": row.verdict,
                "decided_by": row.decided_by,
                "overrode_recommendation": row.overrode_recommendation,
                "without_baseline": row.without_baseline,
            },
        )
        return _to_decision(row)

    async def get_by_hash(self, replay_hash: str) -> Decision | None:
        async with self._sf() as session:
            row = (
                await session.execute(
                    select(PromotionDecisionRow).where(
                        PromotionDecisionRow.replay_hash == replay_hash
                    )
                )
            ).scalar_one_or_none()
            return _to_decision(row) if row is not None else None

    async def history(self, limit: int = 50) -> list[Decision]:
        async with self._sf() as session:
            rows = (
                await session.execute(
                    select(PromotionDecisionRow)
                    .order_by(PromotionDecisionRow.decided_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
            return [_to_decision(r) for r in rows]


def _to_decision(row: PromotionDecisionRow) -> Decision:
    decided_at = row.decided_at
    if decided_at.tzinfo is None:
        # sqlite (tests) hands back naive datetimes; postgres does not.
        decided_at = decided_at.replace(tzinfo=timezone.utc)
    return Decision(
        id=row.id,
        replay_hash=row.replay_hash,
        execution_id=row.execution_id,
        baseline_hash=row.baseline_hash,
        verdict=row.verdict,
        decided_by=row.decided_by,
        reason=row.reason,
        overrode_recommendation=row.overrode_recommendation,
        without_baseline=row.without_baseline,
        quality_regression=row.quality_regression,
        recommendation=dict(row.recommendation or {}),
        decided_at=decided_at,
    )
