from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from atlas.api.deps import AppContainer, get_container
from atlas.features.definitions import FEATURE_NAMES
from atlas.features.definitions import registry as feature_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/meta", tags=["meta"])


@router.get("/features")
async def features(
    container: AppContainer = Depends(get_container),
) -> dict:
    return {
        "feature_schema_version": container.settings.feature_schema_version,
        "features": [
            {
                "name": name,
                "source": feature_registry[name].source,
                "window_seconds": feature_registry[name].window_seconds,
                "low": feature_registry[name].low,
                "high": feature_registry[name].high,
                "default": feature_registry[name].default,
                "description": feature_registry[name].description,
            }
            for name in FEATURE_NAMES
        ],
    }


@router.get("/models")
async def models(
    container: AppContainer = Depends(get_container),
) -> dict:
    from atlas.registry import ModelFamily

    out: dict[str, dict | None] = {}
    for f in ModelFamily:
        v = await container.registry.get_active(f)
        out[f.value] = (
            {
                "version_id": str(v.id),
                "semver": v.semver,
                "stage": v.stage.value,
                "feature_schema_version": v.feature_schema_version,
                "train_metric": v.train_metric,
                "created_at": v.created_at.isoformat(),
                "feature_importance": v.feature_importance,
                "label_source": v.label_source.value,
                "dataset_version": v.dataset_version,
                "historical_window": v.historical_window,
                "dataset_metadata": v.dataset_metadata,
            }
            if v is not None
            else None
        )
    return {"active": out}


@router.get("/strength")
async def strength_state(
    container: AppContainer = Depends(get_container),
) -> dict:
    """Live team-strength engine state (ATLAS-SIM-A).

    The engine, its four state tables and the Explorer sync watcher were
    built with no operational surface at all — nothing answered "is it
    populated, and when did it last sync?". Without that, a cold engine
    (every team on the 1500 seed) is indistinguishable from a warm one
    at the API level, and the similarity signals that depend on it would
    silently be running on defaults.
    """
    if container.strength is None:
        return {"available": False, "reason": "strength_repository_not_configured"}
    return {"available": True, **(await container.strength.overview())}


@router.get("/embeddings")
async def embedding_coverage(
    container: AppContainer = Depends(get_container),
) -> dict:
    """Coexistence of the v1 and v2 memory embeddings.

    The two layouts coexist by design: pgvector columns are
    fixed-dimension, so the 37-dim v2 landed as a SEPARATE column beside
    the frozen 32-dim v1 rather than replacing it (migration 0018). A
    match can therefore hold a v1 row, a v2 row, or both, and which one
    a search uses depends on the requested embedding_version. Coverage
    skew between them is a real operational condition — a v2 corpus
    that is only half backfilled silently returns worse neighbours —
    and it was not observable anywhere.
    """
    from atlas.vector_memory.contracts import (
        EMBEDDING_VERSION,
        EMBEDDING_VERSION_V2,
    )

    known = {
        EMBEDDING_VERSION: {"dimensions": 32, "status": "frozen_v1"},
        EMBEDDING_VERSION_V2: {"dimensions": 37, "status": "candidate_v2"},
    }
    repository = getattr(container, "vector_memory", None)
    if repository is None or not hasattr(repository, "coverage_by_version"):
        return {"available": False, "versions": known, "coverage": []}

    try:
        rows = await repository.coverage_by_version()
    except Exception:
        # Read-only diagnostics must never take down a meta surface.
        logger.exception("embedding_coverage_query_failed")
        return {"available": False, "versions": known, "coverage": []}

    return {
        "available": True,
        "versions": known,
        "coverage": [
            {
                **row,
                **known.get(
                    row["embedding_version"],
                    {"dimensions": None, "status": "unknown"},
                ),
            }
            for row in rows
        ],
    }
