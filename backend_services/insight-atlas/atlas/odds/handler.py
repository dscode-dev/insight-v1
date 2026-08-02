"""OddsHandler — the match.odds ingress path.

Wires the odds subsystem into one idempotent step the canonical
consumer can call per envelope:

    parse → persist history → rebuild features → rebuild context

Persistence is the source of truth (full history); features + context
are derived hot views recomputed from the persisted history on every
snapshot so they always reflect the complete timeline.
"""

from __future__ import annotations

import logging
from uuid import UUID

from atlas.odds.context import OddsContextStore, OddsFeatureStore, build_odds_context
from atlas.odds.features import build_odds_features
from atlas.odds.models import parse_odds_event
from atlas.odds.repository import OddsRepository
from atlas.streaming.canonical_consumer import CanonicalEnvelope

logger = logging.getLogger(__name__)


class OddsHandler:
    def __init__(
        self,
        *,
        repository: OddsRepository,
        feature_store: OddsFeatureStore,
        context_store: OddsContextStore,
        history_limit: int = 500,
    ) -> None:
        self._repo = repository
        self._features = feature_store
        self._context = context_store
        self._limit = history_limit

    async def handle(self, envelope: CanonicalEnvelope) -> None:
        tick = parse_odds_event(envelope.event)

        is_new = await self._repo.record(tick)
        history = await self._repo.history(
            tick.match_id, limit=self._limit
        )

        features = build_odds_features(history)
        await self._features.put(tick.match_id, features)

        context = build_odds_context(tick.match_id, history)
        await self._context.put(tick.match_id, context)

        logger.info(
            "atlas_odds_snapshot_handled",
            extra={
                "match_id": str(tick.match_id),
                "market": tick.market,
                "bookmaker": tick.bookmaker,
                "is_new": is_new,
                "snapshot_count": len(history),
                "idempotency_key": envelope.idempotency_key,
            },
        )

    async def context_for(self, match_id: UUID) -> dict | None:
        return await self._context.get(match_id)
