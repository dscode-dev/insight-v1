"""Runtime ports for canonical intelligence providers.

This sprint intentionally supplies Protocols only.  Existing engines are not
adapted or activated here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlas.intelligence.contracts import (
    Evidence,
    IntelligenceSignal,
    MarketInsight,
    RegimeInsight,
    SimilarityInsight,
    TrendInsight,
)
from atlas.intelligence.kernel import IntelligenceContext


@runtime_checkable
class SignalProvider(Protocol):
    async def signals(self, context: IntelligenceContext) -> list[IntelligenceSignal]: ...


@runtime_checkable
class EvidenceProvider(Protocol):
    async def evidence(self, context: IntelligenceContext) -> list[Evidence]: ...


@runtime_checkable
class TrendProvider(Protocol):
    async def trends(self, context: IntelligenceContext) -> list[TrendInsight]: ...


@runtime_checkable
class RegimeProvider(Protocol):
    async def regime(self, context: IntelligenceContext) -> RegimeInsight | None: ...


@runtime_checkable
class SimilarityProvider(Protocol):
    async def similarity(
        self, context: IntelligenceContext
    ) -> SimilarityInsight | None: ...


@runtime_checkable
class MarketProvider(Protocol):
    async def market(self, context: IntelligenceContext) -> MarketInsight | None: ...

