"""Online similarity probe (ATLAS-VECTOR-B) — the async activation seam.

`TrendDetector.detect` is synchronous, but pgvector search is async. The probe
runs the async query in `TrendIntelligencePipeline.process` (before the sync
detectors) and attaches a `SimilaritySearchResult` to `TrendInputs.similarity`,
which `OracleSimilarityDetector` then consumes. `SimilarityRepository` is the
ONLY search backend — no in-memory index, no alternative repository.

Live-vs-historical embedding parity: the query embedding is built from the
live-tick fields `TrendInputs` carries (context + features), mapped onto the
SAME 32-dim index scheme the persisted embeddings use. It is deliberately
partial — when too few dimensions are populated the probe returns `None` and the
detector emits nothing. The deterministic gates guard neighbour quality.
"""

from __future__ import annotations

import math
from typing import Protocol

from atlas.similarity.contracts import (
    SimilarityContext,
    SimilarityFilters,
    SimilaritySearchRequest,
)
from atlas.trends.models import TrendInputs
from atlas.vector_memory.contracts import EMBEDDING_DIMENSIONS, EMBEDDING_VERSION
from atlas.vector_memory.provenance import feature_schema_version

# Minimum populated dimensions before a live tick is worth a similarity query.
_MIN_SIGNAL_DIMS = 3


class SimilarityContextProvider(Protocol):
    async def context(
        self,
        request: SimilaritySearchRequest,
        *,
        canonical_match_id: str | None = None,
        consumer: str = "unknown",
    ) -> SimilarityContext: ...


def _f(mapping: dict[str, float] | None, *keys: str) -> float | None:
    if not mapping:
        return None
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return float(mapping[key])
    return None


def embed_trend_inputs(inputs: TrendInputs) -> tuple[float, ...] | None:
    """Map the live tick onto the persisted 32-dim scheme (partial by design).

    Returns ``None`` when the tick doesn't carry enough numeric signal to make a
    meaningful vector query. Never fabricates values — absent facets stay 0.

    KNOWN SEMANTIC GAP (tracked for the v2 37-dim migration, NOT fixed
    here because it would mean redesigning the frozen v1 layout): dims
    10 and 28 don't mean the same thing here as in the persisted
    encoder. Dim 10 is `market_pressure` (bookmaker favourite pressure)
    there but receives `pressure_delta` (on-pitch pressure) here; dim 28
    is `scoring_tendency`/expected goals there but receives
    `signal_density` here. The live tick simply has no equivalent of
    those two facets. Because the query vector is otherwise sparse, the
    constant bias term also dominates the cosine ranking. Both are
    resolved properly by moving this probe onto the 15-signal v2 scheme
    (`atlas/vector_memory/embedding.py::from_report_v2`), which has
    real slots for what a live tick actually carries.
    """
    ctx = inputs.context or {}
    feats = inputs.features

    values = [0.0] * EMBEDDING_DIMENSIONS
    # Count DISTINCT SOURCE FACTS, not `put` calls. Dims 8 and 29 both
    # resolved `volatility` first, so a tick carrying that single
    # feature wrote the same number into two slots and counted it
    # twice; together with the constant at dim 11 that reached
    # _MIN_SIGNAL_DIMS (3) on ONE real fact, defeating the
    # "enough signal to query" gate entirely.
    facts: set[str] = set()

    def put(index: int, value: float | None, *, fact: str | None = None) -> None:
        if value is None:
            return
        values[index] = max(0.0, min(1.0, float(value)))
        if fact is not None:
            facts.add(fact)

    volatility = _f(feats, "volatility", "volatility_score")
    competition_volatility = _f(feats, "competition_volatility", "volatility")
    momentum = _f(feats, "momentum_score")
    if momentum is None and isinstance(ctx.get("momentum"), (int, float)):
        momentum = float(ctx["momentum"])
    pressure = _f(feats, "pressure_delta")
    if pressure is None and isinstance(ctx.get("pressure"), (int, float)):
        pressure = float(ctx["pressure"])

    # market_available is a FLAG derived from the presence of odds, not
    # an independent measurement — like the bias term it must not count
    # toward the signal gate.
    put(11, 1.0 if inputs.odds_history else None)
    # Dim 27 in the persisted encoder is |home_form - away_form|, a
    # non-negative MAGNITUDE. `momentum_score` is signed, and the [0,1]
    # clamp silently mapped every negative value to 0.0 —
    # indistinguishable from "absent" while still counting as populated.
    # Taking the magnitude preserves the information and matches what
    # the stored vectors actually hold.
    put(27, abs(momentum) if momentum is not None else None, fact="momentum")
    put(8, volatility, fact="volatility")
    put(29, competition_volatility, fact="competition_volatility")
    put(10, pressure, fact="pressure")
    put(28, _f(feats, "signal_density"), fact="signal_density")
    put(30, _f(feats, "bookmaker_spread", "market_spread"), fact="market_spread")
    values[31] = 1.0  # bias term (matches the encoder), not counted as signal

    if len(facts) < _MIN_SIGNAL_DIMS:
        return None
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 1e-12:
        return None
    return tuple(round(v / norm, 8) for v in values)


class OnlineSimilarityProbe:
    """Builds the query embedding + filters and calls the SimilarityService.

    Consumes the shared service (cache + storage + scoring), NOT the repository
    directly — the probe gets caching/metrics for free and stays consumer-neutral.
    """

    def __init__(
        self,
        service: SimilarityContextProvider,
        *,
        top_k: int = 25,
        minimum_similarity: float = 0.72,
        minimum_neighbors: int = 3,
    ) -> None:
        self._service = service
        self._top_k = top_k
        self._min_similarity = minimum_similarity
        self._min_neighbors = minimum_neighbors

    async def probe(self, inputs: TrendInputs) -> SimilarityContext | None:
        embedding = embed_trend_inputs(inputs)
        if embedding is None:
            return None
        filters = SimilarityFilters(
            embedding_version=EMBEDDING_VERSION,
            feature_schema_version=feature_schema_version(),
        )
        request = SimilaritySearchRequest(
            embedding=embedding,
            filters=filters,
            top_k=self._top_k,
            minimum_similarity=self._min_similarity,
            minimum_neighbors=self._min_neighbors,
        )
        return await self._service.context(
            request,
            canonical_match_id=str(inputs.canonical_match_id),
            consumer="oracle",
        )
