"""The Odds API market → explorer.envelope.v1 (entity_type=odds_snapshot)."""

from __future__ import annotations

from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.normalizers._envelope import build_envelope
from explorer.normalizers.espn import NormalizationError


def _selection_name(outcome_name: str, event: dict[str, Any]) -> str:
    """The API names outcomes by TEAM, not by position.

    `{"name": "Arsenal", "price": 1.8}` has to become `home` or `away`, and
    the only way to tell is by comparing against the event's own team names.
    Keeping the team name would make every fixture its own market vocabulary,
    which nothing downstream could aggregate.
    """
    if outcome_name == event.get("home_team"):
        return "home"
    if outcome_name == event.get("away_team"):
        return "away"
    if outcome_name.lower() == "draw":
        return "draw"
    return outcome_name.lower()


def normalize(artifact: RawArtifact) -> dict[str, Any]:
    raw = artifact.raw
    event = raw.get("_event") or {}
    event_id = event.get("id")
    if not event_id:
        raise NormalizationError("odds-api artifact missing event id")

    selections = []
    for outcome in raw.get("outcomes") or []:
        price = outcome.get("price")
        name = outcome.get("name")
        if not isinstance(price, (int, float)) or price <= 1 or not name:
            # A decimal odd of 1.0 or less pays no more than the stake. It is
            # a placeholder, not a price.
            continue
        selections.append({"name": _selection_name(str(name), event), "price": float(price)})
    if not selections:
        raise NormalizationError("odds-api market carries no usable selection")

    payload = {
        "external_fixture_id": f"oa-{event_id}",
        "bookmaker": raw.get("bookmaker") or "unknown",
        # h2h is this API's name for the 1X2 market. Translated so odds from
        # here and from Football-Data land under one market key.
        "market": "1x2" if raw.get("market") == "h2h" else str(raw.get("market") or "unknown"),
        "captured_at": raw.get("last_update") or artifact.retrieved_at,
        "selections": selections,
    }
    return build_envelope(artifact, confidence=0.95, payload=payload,
                          entity_type="odds_snapshot")
