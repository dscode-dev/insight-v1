"""Operational Replay API (ATLAS-BACKTEST-A2, Stage 3).

Async, non-blocking replay of real historical Explorer datasets through the
production intelligence pipeline. Every source variant converges on the same
adapter → the same ReplayEngine.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from atlas.api.deps import AppContainer, get_container, require_internal_token
from atlas.backtest import (
    scenario_from_dataset,
    scenario_from_interval,
    scenario_from_match,
    scenario_from_mission,
    scenario_from_scope,
    scenario_from_season,
)
from atlas.backtest.approval import ApprovalError, DecisionRequest
from atlas.intelligence.historical import HistoricalScope, load_dataset

router = APIRouter(
    prefix="/backtests",
    tags=["backtests"],
    dependencies=[Depends(require_internal_token)],
)


class BacktestRequest(BaseModel):
    source: str = Field(pattern="^(match|competition|season|interval|dataset|mission)$")
    competition: str | None = None
    season: str | None = None
    year: int | None = None
    uid: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    requester: str = "console"


def _scenario(container: AppContainer, body: BacktestRequest):
    dataset = load_dataset(container.settings.intelligence_dataset_path)
    src = body.source
    if src == "match":
        if not body.uid:
            raise HTTPException(422, "uid required for source=match")
        return scenario_from_match(dataset, body.uid)
    if src == "dataset":
        return scenario_from_dataset(dataset)
    if not body.competition:
        raise HTTPException(422, f"competition required for source={src}")
    if src == "season":
        if not body.season:
            raise HTTPException(422, "season required for source=season")
        return scenario_from_season(dataset, body.competition, body.season)
    if src == "interval":
        if not (body.start and body.end):
            raise HTTPException(422, "start and end required for source=interval")
        return scenario_from_interval(dataset, body.competition, body.start, body.end)
    if src == "mission":
        return scenario_from_mission(dataset, body.competition, body.season)
    # competition
    return scenario_from_scope(
        dataset,
        HistoricalScope(competition=body.competition, year=body.year, season=body.season),
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit_backtest(
    body: BacktestRequest = Body(...),
    container: AppContainer = Depends(get_container),
) -> dict:
    scenario = _scenario(container, body)
    execution = container.replay.submit(
        scenario, dataset_id=scenario.scenario_id, requester=body.requester
    )
    return execution.model_dump(mode="json")


@router.get("")
async def list_backtests(
    limit: int = Query(50, ge=1, le=500),
    container: AppContainer = Depends(get_container),
) -> dict:
    return {"executions": [e.model_dump(mode="json") for e in container.replay.history(limit=limit)]}


@router.get("/decisions")
async def list_decisions(
    limit: int = Query(50, ge=1, le=500),
    container: AppContainer = Depends(get_container),
) -> dict:
    """Audit trail of recorded approve/reject decisions.

    Declared BEFORE `/{execution_id}` on purpose — FastAPI matches in
    declaration order, so the parameterised route would otherwise
    swallow the literal path and try to look up an execution called
    "decisions".
    """
    decisions = await container.approvals.history(limit=limit)
    return {"decisions": [d.to_dict() for d in decisions]}


@router.get("/{execution_id}")
async def get_backtest(
    execution_id: str, container: AppContainer = Depends(get_container)
) -> dict:
    execution = container.replay.status(execution_id)
    if execution is None:
        raise HTTPException(404, "backtest not found")
    return execution.model_dump(mode="json")


@router.get("/{execution_id}/report")
async def get_backtest_report(
    execution_id: str, container: AppContainer = Depends(get_container)
) -> dict:
    report = container.replay.report(execution_id)
    if report is None:
        raise HTTPException(404, "report not available")
    return report.model_dump(mode="json")


@router.get("/{execution_id}/artifacts")
async def get_backtest_artifacts(
    execution_id: str, container: AppContainer = Depends(get_container)
) -> dict:
    artifacts = container.replay.artifacts(execution_id)
    if artifacts is None:
        raise HTTPException(404, "artifacts not available")
    return artifacts.model_dump(mode="json")


@router.get("/{execution_id}/quality")
async def get_backtest_quality(
    execution_id: str, container: AppContainer = Depends(get_container)
) -> dict:
    quality = container.replay.quality(execution_id)
    if quality is None:
        raise HTTPException(404, "quality evaluation not available")
    return quality.model_dump(mode="json")


@router.get("/{execution_id}/manifest")
async def get_backtest_manifest(
    execution_id: str, container: AppContainer = Depends(get_container)
) -> dict:
    manifest = container.replay.manifest(execution_id)
    if manifest is None:
        raise HTTPException(404, "manifest not available")
    return manifest.model_dump(mode="json")


# -- human approval (ATLAS_V1_FROZEN.md: "Human approval remains mandatory") -- #


class DecisionBody(BaseModel):
    verdict: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(min_length=1, max_length=4000)
    # Both default to False so the caller must opt IN to bypassing a
    # gate rule. Defaulting either to True would make the gate advisory.
    override_recommendation: bool = False
    acknowledge_no_baseline: bool = False


_APPROVAL_STATUS = {
    "decision_exists": status.HTTP_409_CONFLICT,
    "override_required": status.HTTP_409_CONFLICT,
    "baseline_required": status.HTTP_409_CONFLICT,
}


@router.post("/{execution_id}/decision", status_code=status.HTTP_201_CREATED)
async def record_decision(
    execution_id: str,
    body: DecisionBody = Body(...),
    x_operator: str | None = Header(default=None),
    container: AppContainer = Depends(get_container),
) -> dict:
    """Record a human's approve/reject on this replay.

    The deciding operator comes from the trusted `X-Operator` header the
    console's server-side layer sets — never from the request body, so a
    caller cannot attribute a decision to someone else.
    """
    if not x_operator or not x_operator.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="operator_header_required"
        )
    quality = container.replay.quality(execution_id)
    if quality is None:
        # No evaluation means nothing was reviewed. Approving here would
        # produce a signed-off record with no evidence behind it.
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="quality_evaluation_not_available"
        )
    try:
        decision = await container.approvals.record(
            request=DecisionRequest(
                verdict=body.verdict,
                reason=body.reason,
                decided_by=x_operator.strip(),
                override_recommendation=body.override_recommendation,
                acknowledge_no_baseline=body.acknowledge_no_baseline,
            ),
            evaluation=quality,
            execution_id=execution_id,
        )
    except ApprovalError as exc:
        raise HTTPException(
            _APPROVAL_STATUS.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return decision.to_dict()


@router.get("/{execution_id}/decision")
async def get_decision(
    execution_id: str, container: AppContainer = Depends(get_container)
) -> dict:
    quality = container.replay.quality(execution_id)
    if quality is None:
        raise HTTPException(404, "quality evaluation not available")
    decision = await container.approvals.get_by_hash(quality.replay_hash)
    if decision is None:
        raise HTTPException(404, "no decision recorded for this replay")
    return decision.to_dict()


@router.delete("/{execution_id}")
async def cancel_backtest(
    execution_id: str, container: AppContainer = Depends(get_container)
) -> dict:
    execution = container.replay.cancel(execution_id)
    if execution is None:
        raise HTTPException(404, "backtest not found")
    return execution.model_dump(mode="json")
