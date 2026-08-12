"""Publication Engine — Sprint 6.2 Part 5.

Decides which signals are worth publishing as intelligence. NOT every
signal is published — publication requires both a configurable
confidence threshold and a configurable impact threshold. No social
posting here; only the decision.
"""

from atlas.publication_engine.engine import PublicationEngine, PublishDecision

__all__ = ["PublicationEngine", "PublishDecision"]
