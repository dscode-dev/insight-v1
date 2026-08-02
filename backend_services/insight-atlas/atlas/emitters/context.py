"""ML_CONTEXT emitter — publishes Atlas outputs onto the derived stream.

Uses Atlas's own `EventEnvelope` wire shape, so the Gateway's
broker tap fans `ML_CONTEXT` events out to clients without extra
plumbing on the Atrium side.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from atlas.streaming.envelope import EventEnvelope
from atlas.streaming.publisher import DerivedPublisher

from atlas.inference.output import MatchContextResponse

logger = logging.getLogger(__name__)


class ContextEmitter:
    def __init__(
        self,
        *,
        publisher: DerivedPublisher,
        region_code: str,
        event_type: str = "ML_CONTEXT",
    ) -> None:
        self._publisher = publisher
        self._region = region_code
        self._event_type = event_type

    async def emit(self, response: MatchContextResponse) -> str | None:
        if (
            response.anomaly is None
            and response.cluster is None
            and response.density is None
            and response.classifier is None
        ):
            return None
        envelope = EventEnvelope(
            event_id=uuid4(),
            match_id=response.match_id,
            region_code=self._region,
            event_type=self._event_type,
            match_version=0,
            ts_ingest=datetime.now(timezone.utc),
            payload=_payload(response),
        )
        try:
            return await self._publisher.publish(envelope)
        except Exception:
            logger.exception(
                "ml_context_emit_failed",
                extra={"match_id": str(response.match_id)},
            )
            return None


def _payload(r: MatchContextResponse) -> dict:
    return {
        "feature_schema_version": r.feature_schema_version,
        "anomaly": r.anomaly.model_dump(mode="json") if r.anomaly else None,
        "cluster": r.cluster.model_dump(mode="json") if r.cluster else None,
        "density": r.density.model_dump(mode="json") if r.density else None,
        "classifier": r.classifier.model_dump(mode="json") if r.classifier else None,
    }
