"""Benchmark ATLAS-VECTOR-A SimilarityRepository against PostgreSQL/pgvector.

Usage:
  ATLAS_DATABASE_URL=postgresql+asyncpg://... poetry run python scripts/atlas_similarity_benchmark.py

The script samples one existing embedding, runs top-k searches and prints
latency plus the query plan. It never writes data.
"""

from __future__ import annotations

import asyncio
import os
import time

from sqlalchemy import text

from atlas.registry import build_engine, build_session_factory
from atlas.similarity import SimilarityFilters, SimilarityRepository, SimilaritySearchRequest
from atlas.vector_memory.contracts import EMBEDDING_DIMENSIONS


async def main() -> None:
    database_url = os.environ.get("ATLAS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("ATLAS_DATABASE_URL or DATABASE_URL is required")

    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    repository = SimilarityRepository(session_factory)
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT embedding::text AS embedding, embedding_version, competition
                    FROM atlas.atlas_vector_memory
                    ORDER BY persisted_at DESC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()
    if row is None:
        raise SystemExit("atlas.atlas_vector_memory has no embeddings")

    embedding = _parse_vector(row["embedding"])
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise SystemExit(f"unexpected embedding dimensions: {len(embedding)}")

    filters = SimilarityFilters(
        embedding_version=row["embedding_version"],
        competition=row["competition"],
    )
    print("ATLAS-VECTOR-A similarity benchmark")
    print(f"embedding_version={filters.embedding_version}")
    print(f"competition={filters.competition}")
    for top_k in (5, 10, 25, 100):
        request = SimilaritySearchRequest(
            embedding=embedding,
            filters=filters,
            top_k=top_k,
            minimum_similarity=0.0,
            minimum_neighbors=min(3, top_k),
        )
        started = time.perf_counter()
        result = await repository.search(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(
            f"top_k={top_k} latency_ms={elapsed_ms:.2f} "
            f"neighbors={len(result.matches)} confidence={result.confidence.confidence}"
        )
        if top_k == 10:
            plan = await repository.explain_nearest(request)
            print("EXPLAIN top_k=10")
            for line in plan:
                print(line)

    await engine.dispose()


def _parse_vector(raw: str) -> tuple[float, ...]:
    return tuple(float(part) for part in raw.strip("[]").split(",") if part)


if __name__ == "__main__":
    asyncio.run(main())
