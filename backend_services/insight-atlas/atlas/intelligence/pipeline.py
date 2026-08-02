"""The real-time intelligence pipeline.

One call per canonical event walks the full intelligence flow and
returns a structured result. Pure orchestration over the engines — each
engine remains independently testable; this composes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from atlas.context_engine import (
    ContextRecalculationEngine,
    MatchContextStore,
    RecalcDecision,
)
from atlas.event_aggregation import AggregationEngine
from atlas.event_impact import EventImpactEngine, ImpactClassification
from atlas.identity import IdentityResolver
from atlas.publication_engine import PublicationEngine, PublishDecision
from atlas.signal_engine import Signal, SignalEngine

# Pressure at/above this level feeds the sustained-pressure aggregation
# (which can emit a PRESSURE_SPIKE once sustained across the window).
PRESSURE_FEED_THRESHOLD = 0.6


@dataclass(frozen=True, slots=True)
class IntelligenceResult:
    canonical_match_id: UUID
    classification: ImpactClassification
    signals: list[Signal]
    decisions: list[PublishDecision]
    recalc: RecalcDecision
    context: dict[str, Any] | None = None
    published: list[PublishDecision] = field(default_factory=list)
    # The match context as it stood BEFORE this tick's recalculation
    # (None when no recalc fired). Trend detectors compare prior vs
    # current to see what is *developing*, not just what *is*.
    prior_context: dict[str, Any] | None = None


class IntelligencePipeline:
    def __init__(
        self,
        *,
        identity_resolver: IdentityResolver,
        impact_engine: EventImpactEngine,
        signal_engine: SignalEngine,
        aggregation_engine: AggregationEngine,
        publication_engine: PublicationEngine,
        context_engine: ContextRecalculationEngine,
        context_store: MatchContextStore,
    ) -> None:
        self._identity = identity_resolver
        self._impact = impact_engine
        self._signals = signal_engine
        self._aggregation = aggregation_engine
        self._publication = publication_engine
        self._context = context_engine
        self._store = context_store

    async def process(
        self,
        event: dict[str, Any],
        *,
        minute: int | None = None,
        odds_shift: bool = False,
        odds_context: dict[str, Any] | None = None,
        market_state: dict[str, Any] | None = None,
    ) -> IntelligenceResult:
        canonical_match_id = await self._identity.resolve_from_event(event)
        classification = self._impact.classify(event)

        signals: list[Signal] = self._signals.generate(
            event=event,
            classification=classification,
            canonical_match_id=canonical_match_id,
        )

        # Aggregate this event's category (e.g. yellow cards → aggressive
        # match). May emit additional, higher-order signals.
        signals.extend(
            await self._aggregation.observe(
                canonical_match_id=canonical_match_id,
                category=classification.category,
            )
        )

        # Context recalculation (event / odds / time triggers).
        recalc = await self._context.evaluate(
            canonical_match_id=canonical_match_id,
            impact=classification.impact,
            minute=minute,
            odds_shift=odds_shift,
        )
        context: dict[str, Any] | None = None
        prior: dict[str, Any] | None = None
        if recalc.recalc:
            prior = await self._store.get(canonical_match_id)
            context = self._context.recompute(
                canonical_match_id=canonical_match_id,
                minute=minute,
                odds_context=odds_context,
                prior=prior,
                market_state=market_state,
                trigger=recalc.trigger,
            )
            await self._store.put(canonical_match_id, context)

            # Sustained high pressure feeds the pressure-spike aggregation.
            if float(context.get("pressure", 0.0)) >= PRESSURE_FEED_THRESHOLD:
                signals.extend(
                    await self._aggregation.observe(
                        canonical_match_id=canonical_match_id,
                        category="pressure_change",
                    )
                )

        decisions = self._publication.decide_many(signals)
        published = [d for d in decisions if d.publish]

        return IntelligenceResult(
            canonical_match_id=canonical_match_id,
            classification=classification,
            signals=signals,
            decisions=decisions,
            recalc=recalc,
            context=context,
            published=published,
            prior_context=prior,
        )
