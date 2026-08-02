"""Event Impact Engine — Sprint 6.2 Part 2.

Classifies any canonical event into an impact tier (LOW/MEDIUM/HIGH/
CRITICAL) using rule-driven, configurable policies. No LLM.
"""

from atlas.event_impact.engine import (
    DEFAULT_IMPACT_POLICY,
    EventImpactEngine,
    Impact,
    ImpactClassification,
    default_categoriser,
)

__all__ = [
    "DEFAULT_IMPACT_POLICY",
    "EventImpactEngine",
    "Impact",
    "ImpactClassification",
    "default_categoriser",
]
