"""Odds context — descriptive market intelligence, NOT prediction.

Builds the latest contextual view Atlas exposes for a match:

  * latest_odds        — newest cross-bookmaker consensus (h2h)
  * market_state       — per market, the latest quote per bookmaker
  * bookmaker_consensus— per market, the mean price across bookmakers

No inference, no probability model — purely the current state of the
observed market, derived from the persisted odds history. Cached in
Redis so the context route can serve it without re-reading Postgres.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import orjson
from redis.asyncio import Redis

from atlas.odds.features import H2H, _latest_per_bookmaker, _mean
from atlas.odds.models import OddsTick

logger = logging.getLogger(__name__)


def build_odds_context(match_id: UUID, history: list[OddsTick]) -> dict[str, Any]:
    """Assemble the descriptive odds context for one match."""
    markets = sorted({t.market for t in history})
    market_state: dict[str, list[dict[str, Any]]] = {}
    bookmaker_consensus: dict[str, dict[str, float]] = {}

    for market in markets:
        market_ticks = [t for t in history if t.market == market]
        latest = _latest_per_bookmaker(market_ticks)
        market_state[market] = [
            {
                "bookmaker": t.bookmaker,
                "home": t.home,
                "draw": t.draw,
                "away": t.away,
                # outcomes[] is propagated verbatim so non-h2h markets
                # (over_under, asian_handicap, btts, corners, cards) keep
                # their full information in the context view.
                "outcomes": t.outcomes(),
                "captured_at": t.captured_at.isoformat(),
            }
            for t in sorted(latest, key=lambda t: t.bookmaker)
        ]
        consensus = {
            "home": _mean([t.home for t in latest if t.home is not None]),
            "draw": _mean([t.draw for t in latest if t.draw is not None]),
            "away": _mean([t.away for t in latest if t.away is not None]),
        }
        bookmaker_consensus[market] = {
            k: v for k, v in consensus.items() if v is not None
        }

    latest_odds = bookmaker_consensus.get(H2H, {})
    last_captured = (
        max(t.captured_at for t in history).isoformat() if history else None
    )

    return {
        "match_id": str(match_id),
        "latest_odds": latest_odds,
        "market_state": market_state,
        "bookmaker_consensus": bookmaker_consensus,
        "markets": markets,
        "bookmaker_count": len({t.bookmaker for t in history}),
        "snapshot_count": len(history),
        "last_captured_at": last_captured,
    }


class OddsFeatureStore:
    """Redis-backed hot store for the latest odds feature vector.

    Kept separate from the ML FeatureStore (which is keyed per match and
    holds the model's positional vector) so the foundational odds
    features never collide with or overwrite the inference snapshot.
    """

    def __init__(self, *, redis: Redis, key_prefix: str, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._r = redis
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, match_id: UUID) -> str:
        return f"{self._prefix}features:{match_id}"

    async def put(self, match_id: UUID, features: dict[str, float]) -> None:
        try:
            await self._r.set(
                self._key(match_id), orjson.dumps(features), ex=self._ttl
            )
        except Exception:
            logger.exception(
                "odds_feature_put_failed", extra={"match_id": str(match_id)}
            )
            raise

    async def get(self, match_id: UUID) -> dict[str, float] | None:
        try:
            raw = await self._r.get(self._key(match_id))
        except Exception:
            logger.exception(
                "odds_feature_get_failed", extra={"match_id": str(match_id)}
            )
            return None
        if raw is None:
            return None
        try:
            return orjson.loads(raw)
        except Exception:
            logger.exception(
                "odds_feature_decode_failed", extra={"match_id": str(match_id)}
            )
            return None


class OddsContextStore:
    """Redis-backed hot store for the latest odds context per match."""

    def __init__(self, *, redis: Redis, key_prefix: str, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._r = redis
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, match_id: UUID) -> str:
        return f"{self._prefix}context:{match_id}"

    async def put(self, match_id: UUID, context: dict[str, Any]) -> None:
        try:
            await self._r.set(
                self._key(match_id), orjson.dumps(context), ex=self._ttl
            )
        except Exception:
            logger.exception(
                "odds_context_put_failed", extra={"match_id": str(match_id)}
            )
            raise

    async def get(self, match_id: UUID) -> dict[str, Any] | None:
        try:
            raw = await self._r.get(self._key(match_id))
        except Exception:
            logger.exception(
                "odds_context_get_failed", extra={"match_id": str(match_id)}
            )
            return None
        if raw is None:
            return None
        try:
            return orjson.loads(raw)
        except Exception:
            logger.exception(
                "odds_context_decode_failed", extra={"match_id": str(match_id)}
            )
            return None
