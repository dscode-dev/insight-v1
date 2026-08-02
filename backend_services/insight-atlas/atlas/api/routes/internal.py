"""Internal endpoints — training trigger, promotion.

All endpoints require the `X-Internal-Token` header. The token is
configurable per environment; in production it is a Secret. In lab the
token is in the ConfigMap and the route is reachable only inside the
cluster (Atlas is ClusterIP-only).
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from atlas.api.deps import AppContainer, get_container, require_internal_token
from atlas.historical import HistoricalDatasetBuilder, load_historical_rows_jsonl
from atlas.registry import ModelFamily
from atlas.training import synthesize_training_set

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


@router.post("/training/{family}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_training(
    family: ModelFamily,
    background: BackgroundTasks,
    container: AppContainer = Depends(get_container),
) -> dict:
    """Kick off training for `family` against synthetic-or-historical
    data. The job runs in a thread pool — the endpoint returns 202
    immediately so the caller doesn't block.

    Real Anvil-driven training will land here once we have enough
    history; until then, synthetic data bootstraps the registry.
    """
    background.add_task(_run_training, container, family)
    return {"status": "accepted", "family": family.value}


@router.post("/training/historical/{family}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_historical_training(
    family: ModelFamily,
    background: BackgroundTasks,
    container: AppContainer = Depends(get_container),
) -> dict:
    """Train from the configured real historical dataset.

    The resulting model version is staged. Operators must inspect the
    training report and call the promotion endpoint explicitly.
    """
    background.add_task(_run_historical_training, container, family)
    return {
        "status": "accepted",
        "family": family.value,
        "dataset_path": container.settings.historical_dataset_path,
        "promotion": "manual",
    }


async def _run_training(container: AppContainer, family: ModelFamily) -> None:
    try:
        # Synthesize until Gateway-mediated Anvil extraction is wired.
        X = await asyncio.to_thread(synthesize_training_set, 800, seed=11)
        result = await container.training.train(family, X)
        if result.succeeded:
            await container.engine.invalidate(family)
            logger.info(
                "training_done",
                extra={
                    "family": family.value,
                    "version": result.version.semver if result.version else None,
                    "metric": result.metrics.get("train_metric"),
                },
            )
        else:
            logger.error(
                "training_failed_in_background",
                extra={"family": family.value, "error": result.error},
            )
    except Exception:
        logger.exception("training_unexpected_failure", extra={"family": family.value})


async def _run_historical_training(container: AppContainer, family: ModelFamily) -> None:
    try:
        rows = await asyncio.to_thread(
            load_historical_rows_jsonl, container.settings.historical_dataset_path
        )
        builder = HistoricalDatasetBuilder(
            feature_schema_version=container.settings.feature_schema_version,
            train_until_year=container.settings.historical_train_until_year,
            validation_year=container.settings.historical_validation_year,
            test_year=container.settings.historical_test_year,
        )
        dataset = await asyncio.to_thread(builder.build, rows)
        result = await container.training.train_historical(
            family, dataset, promote=False
        )
        if result.succeeded:
            logger.info(
                "historical_training_done",
                extra={
                    "family": family.value,
                    "version": result.version.semver if result.version else None,
                    "dataset_version": dataset.version,
                    "metric": result.metrics.get("train_metric"),
                },
            )
        else:
            logger.error(
                "historical_training_failed",
                extra={"family": family.value, "error": result.error},
            )
    except Exception:
        logger.exception(
            "historical_training_unexpected_failure",
            extra={"family": family.value},
        )


@router.post("/models/{version_id}/promote")
async def promote(
    version_id: UUID,
    container: AppContainer = Depends(get_container),
) -> dict:
    version = await container.registry.promote(version_id)
    if version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="version_not_found"
        )
    await container.engine.invalidate(version.family)
    return {
        "version_id": str(version.id),
        "family": version.family.value,
        "stage": version.stage.value,
        "semver": version.semver,
    }
