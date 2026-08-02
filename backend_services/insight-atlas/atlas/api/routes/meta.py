from __future__ import annotations

from fastapi import APIRouter, Depends

from atlas.api.deps import AppContainer, get_container
from atlas.features.definitions import FEATURE_NAMES, registry as feature_registry

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
