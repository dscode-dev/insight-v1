"""Identity resolver (Atlas side).

Resolves a canonical event into a canonical_match_id. Precedence:

  1. Hub-stamped canonical_match_id in the payload (preferred — keeps
     the two services consistent),
  2. exact provider alias,
  3. fuzzy match on competition + normalised teams + kickoff tolerance,
  4. deterministic mint,
  5. fallback to the event's own match_id when team/kickoff signals are
     absent (e.g. standings) so a canonical id always exists.

Every resolution records the provider alias, so provider ids are never
lost.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

from prometheus_client import Counter

from atlas.identity.models import (
    CANONICAL_NAMESPACE,
    CanonicalMatch,
    ProviderMatchIdentity,
    mint,
    normalize,
)
from atlas.identity.registry import IdentityRegistry

logger = logging.getLogger(__name__)

IDENTITY_RESOLUTION_TOTAL = Counter(
    "identity_resolution_total",
    "Cross-provider match identity resolutions, by method.",
    ["method"],
)
IDENTITY_RESOLUTION_FAILURES_TOTAL = Counter(
    "identity_resolution_failures_total",
    "Identity resolutions that fell back due to an error.",
)

DEFAULT_TOLERANCE_SECONDS = 90 * 60


class IdentityResolver:
    def __init__(
        self,
        registry: IdentityRegistry,
        *,
        tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    ) -> None:
        self._registry = registry
        self._tolerance = tolerance_seconds

    async def resolve(self, pmi: ProviderMatchIdentity) -> UUID:
        if pmi.provider and pmi.external_id:
            existing = await self._registry.alias_lookup(pmi.provider, pmi.external_id)
            if existing is not None:
                IDENTITY_RESOLUTION_TOTAL.labels(method="alias").inc()
                return existing

        norm_home = normalize(pmi.home_team)
        norm_away = normalize(pmi.away_team)

        if norm_home and norm_away and pmi.kickoff is not None:
            match = await self._registry.find_within_tolerance(
                pmi.competition_id, norm_home, norm_away, pmi.kickoff, self._tolerance
            )
            if match is not None:
                await self._registry.save(
                    match, provider=pmi.provider, external_id=pmi.external_id
                )
                IDENTITY_RESOLUTION_TOTAL.labels(method="fuzzy").inc()
                return match.canonical_match_id

        canonical_id = mint(pmi.competition_id, norm_home, norm_away, pmi.kickoff)
        await self._registry.save(
            CanonicalMatch(
                canonical_match_id=canonical_id,
                competition_id=pmi.competition_id,
                home_team=norm_home,
                away_team=norm_away,
                kickoff=pmi.kickoff,
            ),
            provider=pmi.provider,
            external_id=pmi.external_id,
        )
        IDENTITY_RESOLUTION_TOTAL.labels(method="mint").inc()
        return canonical_id

    async def resolve_from_event(self, event: dict[str, Any]) -> UUID:
        """Resolve directly from a decoded canonical event. Never raises:
        a failure falls back to the event match_id + counts a failure."""
        try:
            return await self._resolve_from_event(event)
        except Exception:  # noqa: BLE001 — resolution must never break ingestion
            IDENTITY_RESOLUTION_FAILURES_TOTAL.inc()
            logger.exception(
                "identity_resolution_failed",
                extra={"event_id": event.get("event_id")},
            )
            return _fallback_id(event)

    async def _resolve_from_event(self, event: dict[str, Any]) -> UUID:
        payload = event.get("payload") or {}
        provider = str((event.get("source") or {}).get("source_id", ""))
        external = str(payload.get("external_event_id") or event.get("match_id") or "")
        competition_id = _as_uuid(payload.get("competition_id") or event.get("competition_id"))

        # 1. Hub-stamped canonical id — authoritative when present.
        stamped = payload.get("canonical_match_id")
        if stamped:
            canonical_id = UUID(str(stamped))
            await self._registry.save(
                CanonicalMatch(
                    canonical_match_id=canonical_id,
                    competition_id=competition_id,
                    home_team=normalize(_team_name(payload.get("home_team"))),
                    away_team=normalize(_team_name(payload.get("away_team"))),
                    kickoff=_kickoff(payload),
                ),
                provider=provider,
                external_id=external,
                linked_by="stamp",
            )
            IDENTITY_RESOLUTION_TOTAL.labels(method="stamp").inc()
            return canonical_id

        home = _team_name(payload.get("home_team"))
        away = _team_name(payload.get("away_team"))
        if home and away:
            return await self.resolve(
                ProviderMatchIdentity(
                    provider=provider,
                    external_id=external,
                    competition_id=competition_id,
                    home_team=home,
                    away_team=away,
                    kickoff=_kickoff(payload),
                )
            )

        # 5. Fallback — no team/kickoff signals (e.g. standings).
        IDENTITY_RESOLUTION_TOTAL.labels(method="fallback").inc()
        return _fallback_id(event)


def _fallback_id(event: dict[str, Any]) -> UUID:
    match_id = event.get("match_id")
    if match_id:
        try:
            return UUID(str(match_id))
        except (ValueError, TypeError):
            pass
    return uuid5(CANONICAL_NAMESPACE, str(event.get("event_id", "")))


def _team_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        return name if isinstance(name, str) else ""
    return ""


def _as_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _kickoff(payload: dict[str, Any]) -> datetime | None:
    for key in ("commence_time", "scheduled_at", "kickoff"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return None
