"""Backfill deterministic historical embeddings into pgvector storage.

Writes v1 (32-dim, FROZEN) by default. --embedding-version v2 writes the
ATLAS-SIM-A 37-dim layout into the SEPARATE embedding_v2 column
(migration 0018) instead — v1 rows are never touched by a v2 run, and a
v2 run against a corpus that already has v1 rows ADDS a second row per
match rather than overwriting (see PgVectorMemoryRepository.upsert_many_v2).
"""

from __future__ import annotations

import argparse
import asyncio

from atlas.intelligence.historical import load_dataset
from atlas.registry import build_engine, build_session_factory
from atlas.vector_memory import DeterministicEmbeddingEncoder, PgVectorMemoryRepository


async def run(args) -> None:
    dataset = load_dataset(args.matches, args.projection)
    encoder = DeterministicEmbeddingEncoder()
    engine = build_engine(args.database_url)
    repository = PgVectorMemoryRepository(build_session_factory(engine))
    is_v2 = args.embedding_version == "v2"
    encode = encoder.from_record_v2 if is_v2 else encoder.from_record
    upsert = repository.upsert_many_v2 if is_v2 else repository.upsert_many
    try:
        total = 0
        batch = []
        for record in dataset.records:
            batch.append(encode(record))
            if len(batch) >= args.batch_size:
                total += await upsert(batch)
                batch = []
                print(f"vector_backfill={total}")
        total += await upsert(batch)
        print(f"vector_backfill_complete={total} embedding_version={args.embedding_version}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--matches", required=True)
    parser.add_argument("--projection")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--embedding-version", choices=("v1", "v2"), default="v1",
        help="v1 (default, frozen 32-dim) or v2 (ATLAS-SIM-A 37-dim, embedding_v2 column)",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
