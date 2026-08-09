"""Public read API for context inference.

`GET /v1/context/match/{match_id}` — composite context (anomaly + cluster
+ density + classifier) for one match. Atrium proxies this endpoint.

Sprint 0: every request runs through `quarantine_snapshot()` AFTER the
snapshot is built (or read from hot store) but BEFORE inference. A
quarantined snapshot returns HTTP 422 with the reason — the gateway
can surface a descriptive "dados insuficientes" instead of a confident
output produced over defaults.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from atlas.api.deps import AppContainer, get_container
from atlas.contracts import FeatureWindowOrigin
from atlas.features.pipeline import build_snapshot
from atlas.features.snapshot import FeatureSnapshot
from atlas.inference.output import MatchContextResponse
from atlas.validation import quarantine_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/context", tags=["context"])


@router.get("/match/{match_id}", response_model=MatchContextResponse)
async def get_match_context(
    match_id: UUID,
    container: AppContainer = Depends(get_container),
) -> MatchContextResponse:
    # Online path: read hot snapshot, fall back to on-demand build.
    snap = await container.feature_store.get(match_id)
    if snap is None:
        try:
            snap = await build_snapshot(
                match_id=match_id,
                competition_id=None,
                as_of=datetime.now(timezone.utc),
                schema_version=container.settings.feature_schema_version,
                analytics=container.analytics,
                sentiment=container.sentiment,
                # Sprint 0.1 — on-demand REST build is `live` by nature.
                # The periodic worker passes `rolling` (default).
                feature_window_origin=FeatureWindowOrigin.live,
            )
            await container.feature_store.put(snap)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"snapshot_build_failed: {exc}",
            ) from exc

    # Sprint 0 — quarantine BEFORE cache check. A previously cached
    # response could pre-date the new validator, so re-validating
    # the snapshot is cheap insurance.
    decision = quarantine_snapshot(
        snap,
        active_schema_version=container.settings.feature_schema_version,
    )
    if decision.quarantined:
        logger.warning(
            "context_request_quarantined",
            extra={
                "match_id": str(match_id),
                "reason": decision.reason.value,
                "detail": decision.detail,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "snapshot_quarantined",
                "reason": decision.reason.value,
                "detail": decision.detail,
            },
        )

    cached = await container.inference_cache.get(
        match_id, container.settings.feature_schema_version
    )
    if cached is not None:
        try:
            return MatchContextResponse.model_validate(cached)
        except Exception as exc:
            # Stale schema in cache — fall through to fresh inference.
            # Logged (not silently swallowed): if this starts firing on
            # every request it means the cache is effectively disabled
            # and nobody would otherwise notice.
            logger.warning(
                "context_cache_validation_failed",
                extra={"match_id": str(match_id), "err": str(exc)},
            )

    response = await container.engine.context_for(snap)
    await container.inference_cache.put(
        match_id,
        container.settings.feature_schema_version,
        response.model_dump(mode="json"),
    )
    return response


@router.post(
    "/match/{match_id}/snapshot",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=FeatureSnapshot,
)
async def rebuild_snapshot(
    match_id: UUID,
    container: AppContainer = Depends(get_container),
) -> FeatureSnapshot:
    """Force a fresh snapshot build + write to the hot store. Internal /
    Operators can call this when they want to refresh features without
    waiting for the periodic worker."""
    try:
        snap = await build_snapshot(
            match_id=match_id,
            competition_id=None,
            as_of=datetime.now(timezone.utc),
            schema_version=container.settings.feature_schema_version,
            analytics=container.analytics,
            sentiment=container.sentiment,
            feature_window_origin=FeatureWindowOrigin.live,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"snapshot_build_failed: {exc}",
        ) from exc
    await container.feature_store.put(snap)
    return snap
