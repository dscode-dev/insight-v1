"""Migration runner coverage.

We do not need a real ClickHouse for these tests. The runner is responsible
for:
  * Discovering every `.sql` in the migrations directory in order.
  * Rendering `{retention_days}` per table from settings.
  * Splitting each file into individual statements stripped of comments.
  * Calling `client.command(...)` for each.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any


from anvil.clickhouse.client import run_migrations
from anvil.config.settings import _reset_settings_cache


class RecordingClient:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def insert(self, *args, **kwargs) -> None:  # pragma: no cover
        raise AssertionError("run_migrations must not call insert()")

    async def command(self, sql: str) -> Any:
        self.commands.append(sql)
        return None

    async def ping(self) -> bool:  # pragma: no cover
        return True

    async def close(self) -> None:  # pragma: no cover
        return None


def _make_settings():
    # Reset to make sure env overrides land.
    _reset_settings_cache()
    os.environ.setdefault("REDIS_URL", "redis://test:0")
    os.environ.setdefault("CLICKHOUSE_HOST", "ch.test")
    os.environ.setdefault("CLICKHOUSE_DATABASE", "insight")
    os.environ.setdefault("RETENTION_DAYS_MARKET_SNAPSHOTS", "30")
    os.environ.setdefault("RETENTION_DAYS_METRIC_TICKS", "45")
    os.environ.setdefault("RETENTION_DAYS_HUMAN_SIGNALS", "60")
    from anvil.config import get_settings

    _reset_settings_cache()
    return get_settings()


def test_runs_every_migration_in_order():
    async def go():
        settings = _make_settings()
        client = RecordingClient()
        executed = await run_migrations(client, settings)
        # We have 4 migration files: 0001..0004.
        assert len(client.commands) >= 4
        # First command should be the CREATE DATABASE.
        assert "CREATE DATABASE" in client.commands[0].upper()
        # Tables must all be present somewhere in the executed SQL.
        joined = "\n".join(client.commands).lower()
        assert "market_snapshots" in joined
        assert "metric_ticks" in joined
        assert "human_signals" in joined
        # Sanity: every executed command came back in the return value.
        assert client.commands == executed

    asyncio.run(go())


def test_retention_template_is_rendered_per_table():
    async def go():
        settings = _make_settings()
        client = RecordingClient()
        await run_migrations(client, settings)

        joined = "\n".join(client.commands)
        # Different days for each table from env above.
        assert "INTERVAL 30 DAY" in joined  # market_snapshots
        assert "INTERVAL 45 DAY" in joined  # metric_ticks
        assert "INTERVAL 60 DAY" in joined  # human_signals
        # No unrendered placeholder leaked through.
        assert "{retention_days}" not in joined

    asyncio.run(go())


def test_comments_are_stripped_from_statements():
    async def go():
        settings = _make_settings()
        client = RecordingClient()
        await run_migrations(client, settings)
        for stmt in client.commands:
            for line in stmt.splitlines():
                assert not line.strip().startswith("--"), (
                    f"comment leaked into statement: {line!r}"
                )

    asyncio.run(go())
