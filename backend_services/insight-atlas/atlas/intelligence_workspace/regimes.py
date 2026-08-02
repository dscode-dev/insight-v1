"""Deterministic football regime routing.

This module does not load or activate candidates. It only classifies historical
football contexts so operators can see which unpromoted candidate would be
eligible after a future promotion decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LEAGUE_COMPETITIONS = {
    "premier_league",
    "la_liga",
    "serie_a",
    "bundesliga",
    "ligue_1",
    "brasileirao_serie_a",
}
CONTINENTAL_COMPETITIONS = {
    "champions_league",
    "europa_league",
    "libertadores",
    "sudamericana",
}
INTERNATIONAL_COMPETITIONS = {"world_cup", "euro", "copa_america"}

REGIME_BY_COMPETITION = {
    **{competition: "league" for competition in LEAGUE_COMPETITIONS},
    **{competition: "continental" for competition in CONTINENTAL_COMPETITIONS},
    **{competition: "international" for competition in INTERNATIONAL_COMPETITIONS},
}

CANDIDATE_BY_REGIME = {
    "league": "outcome_league_v1",
    "continental": "outcome_continental_v1",
    "international": "outcome_international_v1",
    "global": "outcome_v3",
}

CONFIDENCE_MODIFIER_BY_COMPETITION = {
    "world_cup": 0.88,
    "euro": 0.88,
    "copa_america": 0.88,
    "libertadores": 0.92,
    "sudamericana": 0.92,
}


@dataclass(frozen=True)
class RegimeDecision:
    regime_id: str
    candidate: str
    confidence_modifier: float
    activated: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime_id": self.regime_id,
            "candidate": self.candidate,
            "confidence_modifier": self.confidence_modifier,
            "activated": self.activated,
            "reason": self.reason,
        }


def detect_regime(competition: str | None) -> RegimeDecision:
    key = (competition or "").strip().lower()
    regime = REGIME_BY_COMPETITION.get(key, "global")
    if regime == "global":
        return RegimeDecision(
            regime_id="global",
            candidate=CANDIDATE_BY_REGIME["global"],
            confidence_modifier=0.75,
            activated=False,
            reason="unknown competition; keep global fallback only",
        )
    return RegimeDecision(
        regime_id=regime,
        candidate=CANDIDATE_BY_REGIME[regime],
        confidence_modifier=CONFIDENCE_MODIFIER_BY_COMPETITION.get(key, 1.0),
        activated=False,
        reason="candidate routing implemented for review; no runtime activation",
    )


def regime_inventory() -> dict[str, list[str]]:
    return {
        "league": sorted(LEAGUE_COMPETITIONS),
        "continental": sorted(CONTINENTAL_COMPETITIONS),
        "international": sorted(INTERNATIONAL_COMPETITIONS),
    }

