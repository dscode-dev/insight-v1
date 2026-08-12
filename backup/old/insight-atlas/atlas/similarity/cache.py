"""Transparent, version-aware TTL cache for similarity results (Stage 2).

Avoids repeated pgvector queries for near-identical requests within a short
window. The key folds in every version + domain facet, so a version change
yields a different key — stale results after a version bump are impossible.
Purely an in-process performance layer; fully transparent to consumers.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict

from atlas.similarity.contracts import SimilarityContext, SimilaritySearchRequest


def _embedding_hash(embedding: tuple[float, ...]) -> str:
    raw = ",".join(f"{v:.6f}" for v in embedding).encode("utf-8")
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()[:16]


def cache_key(
    request: SimilaritySearchRequest,
    *,
    canonical_match_id: str | None = None,
) -> str:
    f = request.filters
    return "|".join(
        str(part)
        for part in (
            canonical_match_id or "-",
            _embedding_hash(request.embedding),
            f.embedding_version,
            f.feature_schema_version or "-",
            f.competition or "-",
            f.season or "-",
            f.market_type or "-",
            f.match_phase or "-",
            request.top_k,
            f"{request.minimum_similarity:.4f}",
            # `minimum_neighbors` is NOT merely a display field: it
            # drives `coverage = len(matches) / minimum_neighbors`,
            # which feeds `confidence`, and it is echoed into
            # `SimilarityConfidence.minimum_neighbors` — which
            # OracleSimilarityDetector gates on directly. Leaving it out
            # of the key meant two requests differing only in this value
            # collided, and the second silently received the first's
            # coverage/confidence (e.g. 1.0 instead of 0.4 for the same
            # four neighbours), which could flip an Oracle gate.
            request.minimum_neighbors,
        )
    )


class SimilarityCache:
    """Bounded LRU + TTL cache. Not thread-shared state beyond the event loop."""

    def __init__(self, *, ttl_seconds: float = 45.0, max_entries: int = 2048) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._store: OrderedDict[str, tuple[float, SimilarityContext]] = OrderedDict()

    def get(self, key: str) -> SimilarityContext | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)  # LRU touch
        return value

    def put(self, key: str, value: SimilarityContext) -> None:
        if self._ttl <= 0:
            return
        self._store[key] = (time.monotonic() + self._ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)  # evict oldest

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
