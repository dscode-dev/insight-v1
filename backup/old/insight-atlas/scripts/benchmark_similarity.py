"""ATLAS-VECTOR-B — pgvector online similarity benchmark (Stage 8).

Runs the production SimilarityRepository against a REAL Postgres+pgvector with
already-persisted `atlas.atlas_vector_memory` rows. Measures, for Top-5/10/25/
100: latency (p50/p95), neighbour quality (best/avg similarity), confidence,
filter selectivity (rows returned vs top_k), and confirms HNSW index usage via
EXPLAIN. No synthetic data — point it at a populated database.

    DATABASE_URL=postgresql+asyncpg://... python scripts/benchmark_similarity.py

Cannot run in an environment without Postgres+pgvector.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas.similarity.cache import SimilarityCache
from atlas.similarity.contracts import SimilarityFilters, SimilaritySearchRequest
from atlas.similarity.repository import SimilarityRepository
from atlas.similarity.service import SimilarityService
from atlas.vector_memory.contracts import EMBEDDING_DIMENSIONS, EMBEDDING_VERSION

TOP_KS = (5, 10, 25, 100)
ITERATIONS = 50


async def _sample_embedding(sf: async_sessionmaker) -> tuple[float, ...]:
    """Use a real persisted vector as the query (honest neighbour distances)."""
    from sqlalchemy import text

    async with sf() as session:
        row = (
            await session.execute(
                text(
                    "SELECT embedding FROM atlas.atlas_vector_memory "
                    "WHERE embedding_version = :ev ORDER BY created_at DESC LIMIT 1"
                ),
                {"ev": EMBEDDING_VERSION},
            )
        ).first()
    if row is None:
        raise SystemExit("no persisted vectors — populate atlas_vector_memory first")
    raw = str(row[0]).strip("[]")
    return tuple(float(x) for x in raw.split(","))[:EMBEDDING_DIMENSIONS]


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    repo = SimilarityRepository(sf)
    embedding = await _sample_embedding(sf)
    filters = SimilarityFilters(embedding_version=EMBEDDING_VERSION)

    print(f"# pgvector similarity benchmark ({ITERATIONS} iters/topk)\n")
    for top_k in TOP_KS:
        request = SimilaritySearchRequest(
            embedding=embedding, filters=filters, top_k=top_k, minimum_similarity=0.0
        )
        latencies: list[float] = []
        result = None
        for _ in range(ITERATIONS):
            started = time.perf_counter()
            result = await repo.search(request)
            latencies.append((time.perf_counter() - started) * 1000.0)
        assert result is not None
        sims = [m.similarity for m in result.matches] or [0.0]
        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(0.95 * (len(latencies) - 1))]
        print(
            f"top_k={top_k:<4} "
            f"p50={p50:6.2f}ms p95={p95:6.2f}ms "
            f"returned={len(result.matches):<4}(sel={len(result.matches)/top_k:.2f}) "
            f"best_sim={max(sims):.3f} avg_sim={sum(sims)/len(sims):.3f} "
            f"confidence={result.confidence.confidence:.3f}"
        )

    # -- Service: cache miss vs hit + batch (ATLAS-SIMILARITY-A) --
    service = SimilarityService(repo, cache=SimilarityCache(ttl_seconds=60))
    base = SimilaritySearchRequest(
        embedding=embedding, filters=filters, top_k=25, minimum_similarity=0.0
    )
    t0 = time.perf_counter()
    await service.context(base, canonical_match_id="bench")
    miss_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    await service.context(base, canonical_match_id="bench")
    hit_ms = (time.perf_counter() - t0) * 1000.0
    batch_requests = [base] * 10
    t0 = time.perf_counter()
    await service.batch_context(batch_requests, canonical_match_ids=[f"b{i}" for i in range(10)])
    batch_ms = (time.perf_counter() - t0) * 1000.0
    print(
        f"\n# service: cache_miss={miss_ms:.2f}ms cache_hit={hit_ms:.2f}ms "
        f"batch(10)={batch_ms:.2f}ms ({batch_ms/10:.2f}ms/req)"
    )

    plan = await repo.explain_nearest(
        SimilaritySearchRequest(embedding=embedding, filters=filters, top_k=25)
    )
    uses_hnsw = any("hnsw" in line.lower() or "ix_atlas_vector_memory_embedding" in line for line in plan)
    print(f"\n# HNSW index used: {uses_hnsw}")
    print("\n".join(plan))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
