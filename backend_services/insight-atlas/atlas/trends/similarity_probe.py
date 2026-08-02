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
    """
    ctx = inputs.context or {}
    feats = inputs.features

    values = [0.0] * EMBEDDING_DIMENSIONS
    populated = 0

    def put(index: int, value: float | None) -> None:
        nonlocal populated
        if value is None:
            return
        values[index] = max(0.0, min(1.0, float(value)))
        populated += 1

    # 11 market_available, 27 momentum, 29 volatility, 30 market spread —
    # the dimensions a live tick can honestly fill.
    put(11, 1.0 if inputs.odds_history else None)
    put(27, _f(feats, "momentum_score") or (ctx.get("momentum") if isinstance(ctx.get("momentum"), (int, float)) else None))
    put(8, _f(feats, "volatility", "volatility_score"))
    put(29, _f(feats, "volatility", "competition_volatility"))
    put(10, _f(feats, "pressure_delta") or (ctx.get("pressure") if isinstance(ctx.get("pressure"), (int, float)) else None))
    put(28, _f(feats, "signal_density"))
    put(30, _f(feats, "bookmaker_spread", "market_spread"))
    values[31] = 1.0  # bias term (matches the encoder), not counted as signal

    if populated < _MIN_SIGNAL_DIMS:
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
