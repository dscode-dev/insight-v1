"""Odds domain models + canonical-event parsing.

Atlas consumes `match.odds` canonical events off
`insight:stream:events:odds`. Each event is ONE snapshot of one
(match, market, bookmaker) lane. This module turns the wire payload
into a typed `OddsTick` and validates the minimum odds contract — the
streaming consumer's generic validation handles the envelope shape;
this adds the odds-specific semantics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OddsParseError(ValueError):
    """Raised when a match.odds event cannot be parsed into an OddsTick."""


class OddsTick(BaseModel):
    """One persisted/queried odds snapshot.

    `match_id` is the STABLE per-match grouping key carried in the
    payload (a deterministic UUID over the provider's event id) — used
    to assemble a match's odds timeline across snapshots. It is
    intentionally distinct from the canonical envelope's
    snapshot-scoped match_id.
    """

    model_config = ConfigDict(frozen=True)

    canonical_event_id: UUID
    provider: str
    competition_id: UUID | None
    match_id: UUID
    market: str
    bookmaker: str
    home: float | None = None
    draw: float | None = None
    away: float | None = None
    captured_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    def outcomes(self) -> list[dict[str, Any]]:
        """The full outcome list — the source of truth for every market.

        h2h home/draw/away are convenience projections; non-h2h markets
        (over_under, asian_handicap, btts, corners, cards, …) carry all
        their information here (name, price, and the line via `point`).
        """
        raw = self.payload.get("outcomes")
        return [o for o in raw if isinstance(o, dict)] if isinstance(raw, list) else []


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_captured_at(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise OddsParseError(f"invalid captured_at: {raw!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_odds_event(event: dict[str, Any]) -> OddsTick:
    """Build an OddsTick from a decoded canonical `match.odds` event.

    Raises OddsParseError on any missing/invalid required field so the
    consumer can route the entry to the DLQ rather than persist a
    half-formed snapshot.
    """
    try:
        canonical_event_id = UUID(str(event["event_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise OddsParseError("event_id missing or invalid") from exc

    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise OddsParseError("payload missing or invalid")

    market = payload.get("market")
    bookmaker = payload.get("bookmaker")
    if not isinstance(market, str) or not market:
        raise OddsParseError("payload.market missing")
    if not isinstance(bookmaker, str) or not bookmaker:
        raise OddsParseError("payload.bookmaker missing")

    # Prefer the stable per-match id in the payload; fall back to the
    # canonical envelope's match_id when absent (defensive).
    match_id_raw = payload.get("match_id") or event.get("match_id")
    try:
        match_id = UUID(str(match_id_raw))
    except (ValueError, TypeError) as exc:
        raise OddsParseError("match_id missing or invalid") from exc

    competition_raw = payload.get("competition_id") or event.get("competition_id")
    competition_id: UUID | None
    try:
        competition_id = UUID(str(competition_raw)) if competition_raw else None
    except (ValueError, TypeError):
        competition_id = None

    captured_at = _parse_captured_at(
        payload.get("captured_at") or event.get("occurred_at")
    )

    return OddsTick(
        canonical_event_id=canonical_event_id,
        provider=str(payload.get("provider", "")),
        competition_id=competition_id,
        match_id=match_id,
        market=market,
        bookmaker=bookmaker,
        home=_coerce_float(payload.get("home")),
        draw=_coerce_float(payload.get("draw")),
        away=_coerce_float(payload.get("away")),
        captured_at=captured_at,
        payload=payload,
    )
