"""Backfill deterministic historical embeddings into pgvector storage."""

from __future__ import annotations

import argparse
import asyncio

from atlas.intelligence.historical import load_dataset
from atlas.registry import build_engine, build_session_factory
from atlas.vector_memory import (
    DeterministicEmbeddingEncoder,
    PgVectorMemoryRepository,
)


async def run(args) -> None:
    dataset = load_dataset(args.matches, args.projection)
    encoder = DeterministicEmbeddingEncoder()
    engine = build_engine(args.database_url)
    repository = PgVectorMemoryRepository(build_session_factory(engine))
    try:
        total = 0
        batch = []
        for record in dataset.records:
            batch.append(encoder.from_record(record))
            if len(batch) >= args.batch_size:
                total += await repository.upsert_many(batch)
                batch = []
                print(f"vector_backfill={total}")
        total += await repository.upsert_many(batch)
        print(f"vector_backfill_complete={total}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--matches", required=True)
    parser.add_argument("--projection")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
