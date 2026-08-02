"""Operational Replay API (ATLAS-BACKTEST-A2, Stage 3).

Async, non-blocking replay of real historical Explorer datasets through the
production intelligence pipeline. Every source variant converges on the same
adapter → the same ReplayEngine.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
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


@router.delete("/{execution_id}")
async def cancel_backtest(
    execution_id: str, container: AppContainer = Depends(get_container)
) -> dict:
    execution = container.replay.cancel(execution_id)
    if execution is None:
        raise HTTPException(404, "backtest not found")
    return execution.model_dump(mode="json")
