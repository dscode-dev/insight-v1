"""atlas-migrate — V1.2 packaging: applies migrations/sql/NNNN_*.sql in
lexical order against DATABASE_URL.

The SQL files are idempotent (IF NOT EXISTS / ON CONFLICT), and an
applied-versions table (atlas.schema_migrations) records progress so
deploy logs show exactly what ran when. Runs as a one-shot compose
service from the Atlas image, before the app starts:

    python scripts/migrate.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine

from atlas.registry.models import Base

BOOTSTRAP = """
CREATE SCHEMA IF NOT EXISTS atlas;
CREATE TABLE IF NOT EXISTS atlas.schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("atlas-migrate: DATABASE_URL required")
    # SQLAlchemy-style URLs (postgresql+asyncpg://) → asyncpg plain.
    return dsn.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgresql://"
    )


async def run() -> None:
    base = Path(os.environ.get("MIGRATIONS_DIR", "migrations/sql"))
    files = sorted(base.glob("*.sql"))
    if not files:
        raise SystemExit(f"atlas-migrate: no migrations found in {base}")

    # The ORM tables target schema "atlas", so create that namespace before
    # Base.metadata.create_all on a fresh database.
    conn = await asyncpg.connect(_dsn())
    try:
        await conn.execute(BOOTSTRAP)
    finally:
        await conn.close()

    # Bootstrap the current ORM-owned base tables. The SQL migration history
    # below remains authoritative for additive indexes, backfills and audit
    # records.
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as sqlalchemy_conn:
            await sqlalchemy_conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

    conn = await asyncpg.connect(_dsn())
    try:
        for f in files:
            done = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM atlas.schema_migrations WHERE filename=$1)",
                f.name,
            )
            if done:
                print("skip ", f.name)
                continue
            async with conn.transaction():
                await conn.execute(f.read_text())
                await conn.execute(
                    "INSERT INTO atlas.schema_migrations (filename) VALUES ($1)",
                    f.name,
                )
            print("apply", f.name)
        print("atlas migrations up to date")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 — one-shot: fail loud, exit 1
        print(f"atlas-migrate: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
