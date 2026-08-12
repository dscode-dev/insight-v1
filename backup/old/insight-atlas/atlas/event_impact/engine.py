"""Event Impact Engine — rule-driven impact classification.

Maps a canonical event to an impact tier through two configurable
layers:

  1. a *categoriser* that derives a stable category string from the
     event (event_type + payload), and
  2. an *impact policy* that maps category → Impact.

Both are injectable, so future rules are configuration, not code. The
engine never calls an LLM and never performs inference — it is a pure
deterministic classifier.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Callable

from prometheus_client import Counter

EVENT_IMPACT_TOTAL = Counter(
    "event_impact_total",
    "Canonical events classified by the Event Impact Engine.",
    ["impact", "category"],
)


class Impact(enum.IntEnum):
    """Impact tiers, ordered so thresholds compare numerically."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class ImpactClassification:
    impact: Impact
    category: str
    reason: str


# Default category → impact policy (Sprint 6.2 spec). Configurable: pass
# a custom mapping to EventImpactEngine.
DEFAULT_IMPACT_POLICY: dict[str, Impact] = {
    # CRITICAL — match-defining moments.
    "goal": Impact.CRITICAL,
    "red_card": Impact.CRITICAL,
    "match_suspended": Impact.CRITICAL,
    "match_resumed": Impact.CRITICAL,
    "halftime": Impact.CRITICAL,
    "fulltime": Impact.CRITICAL,
    "result": Impact.CRITICAL,
    # HIGH — strong contextual shifts.
    "penalty": Impact.HIGH,
    "injury": Impact.HIGH,
    "key_substitution": Impact.HIGH,
    "odds": Impact.HIGH,
    # MEDIUM — meaningful but not decisive.
    "yellow_card": Impact.MEDIUM,
    "substitution": Impact.MEDIUM,
    "pressure_change": Impact.MEDIUM,
    "momentum_shift": Impact.MEDIUM,
    # LOW — routine play / scheduling / standings.
    "throw_in": Impact.LOW,
    "goal_kick": Impact.LOW,
    "corner": Impact.LOW,
    "foul": Impact.LOW,
    "offside": Impact.LOW,
    "fixture": Impact.LOW,
    "standings": Impact.LOW,
}

Categoriser = Callable[[dict[str, Any]], str]


def default_categoriser(event: dict[str, Any]) -> str:
    """Derive a category from a canonical event.

    Precedence:
      1. an explicit `payload.category` (future provider events may carry
         a precise category directly),
      2. the event_type suffix, with a few payload-aware refinements
         (a red card vs yellow card; a key-player substitution).

    Provider-agnostic: keys on the canonical event_type taxonomy, never
    on a specific provider.
    """
    payload = event.get("payload") or {}
    explicit = payload.get("category")
    if isinstance(explicit, str) and explicit:
        return explicit

    event_type = str(event.get("event_type", ""))
    if event_type.startswith("competition."):
        return "standings"
    if not event_type.startswith("match."):
        return "unknown"

    suffix = event_type.split(".", 1)[1]

    if suffix == "card":
        return "red_card" if str(payload.get("card", "")).lower() == "red" else "yellow_card"
    if suffix == "substitution":
        return "key_substitution" if payload.get("key_player") else "substitution"

    # Direct suffixes already aligned with the policy keys.
    known = {
        "goal",
        "red_card",
        "yellow_card",
        "penalty",
        "injury",
        "halftime",
        "fulltime",
        "result",
        "fixture",
        "odds",
        "suspended",
        "resumed",
    }
    if suffix in known:
        return {"suspended": "match_suspended", "resumed": "match_resumed"}.get(suffix, suffix)
    return "unknown"


class EventImpactEngine:
    """Centralised, rule-driven impact classifier."""

    def __init__(
        self,
        *,
        policy: dict[str, Impact] | None = None,
        categoriser: Categoriser | None = None,
        default_impact: Impact = Impact.LOW,
    ) -> None:
        self._policy = dict(policy) if policy is not None else dict(DEFAULT_IMPACT_POLICY)
        self._categoriser = categoriser or default_categoriser
        self._default = default_impact

    def classify(self, event: dict[str, Any]) -> ImpactClassification:
        category = self._categoriser(event)
        impact = self._policy.get(category, self._default)
        EVENT_IMPACT_TOTAL.labels(impact=impact.label, category=category).inc()
        return ImpactClassification(
            impact=impact, category=category, reason=f"category={category}"
        )
