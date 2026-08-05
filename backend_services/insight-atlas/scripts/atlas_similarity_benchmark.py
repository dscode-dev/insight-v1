"""Benchmark ATLAS-VECTOR-A SimilarityRepository against PostgreSQL/pgvector.

Usage:
  ATLAS_DATABASE_URL=postgresql+asyncpg://... poetry run python scripts/atlas_similarity_benchmark.py
  ATLAS_DATABASE_URL=... poetry run python scripts/atlas_similarity_benchmark.py --embedding-version v2

The script samples one existing embedding, runs top-k searches and prints
latency plus the query plan. It never writes data.

--embedding-version v1 (default) benchmarks the frozen 32-dim column/HNSW
index (`embedding`); v2 benchmarks the ATLAS-SIM-A 37-dim column/HNSW
index (`embedding_v2`, migration 0018) instead — SimilarityRepository
picks the physical column from `filters.embedding_version` automatically,
this script just needs to sample from the matching column and validate
against the matching dimension count.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time

from sqlalchemy import text

from atlas.registry import build_engine, build_session_factory
from atlas.similarity import (
    SimilarityFilters,
    SimilarityRepository,
    SimilaritySearchRequest,
)
from atlas.vector_memory.contracts import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_DIMENSIONS_V2,
    EMBEDDING_VERSION_V2,
)


async def main(embedding_version_arg: str) -> None:
    database_url = os.environ.get("ATLAS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("ATLAS_DATABASE_URL or DATABASE_URL is required")

    is_v2 = embedding_version_arg == "v2"
    column = "embedding_v2" if is_v2 else "embedding"
    expected_dimensions = EMBEDDING_DIMENSIONS_V2 if is_v2 else EMBEDDING_DIMENSIONS

    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    repository = SimilarityRepository(session_factory)
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    f"""
                    SELECT {column}::text AS embedding, embedding_version, competition
                    FROM atlas.atlas_vector_memory
                    WHERE {column} IS NOT NULL
                    ORDER BY persisted_at DESC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()
    if row is None:
        raise SystemExit(
            f"atlas.atlas_vector_memory has no {embedding_version_arg} embeddings "
            f"({column} is NULL on every row)"
        )

    embedding = _parse_vector(row["embedding"])
    if len(embedding) != expected_dimensions:
        raise SystemExit(f"unexpected embedding dimensions: {len(embedding)}")

    filters = SimilarityFilters(
        embedding_version=row["embedding_version"],
        competition=row["competition"],
    )
    if is_v2 and filters.embedding_version != EMBEDDING_VERSION_V2:
        raise SystemExit(
            f"row has embedding_v2 set but embedding_version={filters.embedding_version!r} "
            f"(expected {EMBEDDING_VERSION_V2!r}) — data looks inconsistent"
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--embedding-version", choices=("v1", "v2"), default="v1",
        help="v1 (default, frozen 32-dim `embedding` column) or v2 (ATLAS-SIM-A 37-dim `embedding_v2`)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.embedding_version))
