"""Pure context recomputation.

Recalculates the descriptive match context — game state, momentum,
pressure and market-implied contextual probabilities — from the current
minute plus the latest stored odds/feature context. No new events
required, no prediction model: the contextual probabilities are the
overround-normalised implied probabilities of the bookmaker consensus
(descriptive market intelligence, not a forecast).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID


def game_state(minute: int | None) -> str:
    if minute is None or minute <= 0:
        return "pre_match"
    if minute <= 15:
        return "early"
    if minute <= 45:
        return "first_half"
    if minute <= 75:
        return "second_half"
    if minute <= 90:
        return "late"
    return "stoppage"


def implied_probabilities(latest_odds: dict[str, Any]) -> dict[str, float]:
    """Normalise decimal odds into implied probabilities, removing the
    bookmaker overround. {home: 1.8, draw: 3.5, away: 4.2} → probs."""
    inv: dict[str, float] = {}
    for outcome, price in latest_odds.items():
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        if p > 0:
            inv[outcome] = 1.0 / p
    total = sum(inv.values())
    if total <= 0:
        return {}
    return {k: round(v / total, 4) for k, v in inv.items()}


def _pressure(probs: dict[str, float], minute: int | None, prior_pressure: float) -> float:
    if not probs:
        # No fresh market signal — decay the prior pressure slightly.
        return round(prior_pressure * 0.95, 4)
    spread = max(probs.values()) - min(probs.values())
    lateness = min(max((minute or 0) / 90.0, 0.0), 1.2)
    return round(min(1.0, spread * (0.5 + 0.5 * lateness)), 4)


def recompute_context(
    *,
    canonical_match_id: UUID,
    minute: int | None,
    odds_context: dict[str, Any] | None = None,
    prior: dict[str, Any] | None = None,
    market_state: dict[str, Any] | None = None,
    intelligence_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prior = prior or {}
    probs: dict[str, float] = {}
    if odds_context:
        latest = odds_context.get("latest_odds") or {}
        if isinstance(latest, dict):
            probs = implied_probabilities(latest)
    if not probs:
        # No fresh odds — carry the last known implied probabilities so a
        # time-driven checkpoint still reports a contextual probability.
        carried = prior.get("contextual_probabilities")
        if isinstance(carried, dict):
            probs = dict(carried)

    prior_pressure = float(prior.get("pressure", 0.0) or 0.0)
    prior_momentum = float(prior.get("momentum", 0.0) or 0.0)

    # Market intelligence (Magnus Absorption): fresh market_state when
    # this recalculation carried one; otherwise carry the last known
    # view forward (same posture as contextual_probabilities).
    if market_state is None:
        carried_market = prior.get("market_state")
        market_state = dict(carried_market) if isinstance(carried_market, dict) else None

    # Intelligence maturity (Sprint 1.5): same carry-forward posture for
    # the competition/meta intelligence block.
    if intelligence_state is None:
        carried_intel = prior.get("intelligence_state")
        intelligence_state = (
            dict(carried_intel) if isinstance(carried_intel, dict) else None
        )

    return {
        "canonical_match_id": str(canonical_match_id),
        "minute": minute,
        "game_state": game_state(minute),
        # Momentum decays toward neutral when no new events arrive — the
        # whole point of time-driven recalculation.
        "momentum": round(prior_momentum * 0.9, 4),
        "pressure": _pressure(probs, minute, prior_pressure),
        "contextual_probabilities": probs,
        "market_state": market_state,
        "intelligence_state": intelligence_state,
        "recomputed_at": datetime.now(timezone.utc).isoformat(),
    }
