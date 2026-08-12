"""Async ClickHouse client wrapper + migration runner.

This module wraps `clickhouse_connect` so the rest of Anvil never imports
the third-party client directly. That gives us:
  * a single seam for connection lifecycle (open / close / reconnect),
  * a single seam for retry policy / error mapping,
  * a deterministic test surface (the batch inserter takes a `ClickHouseClient`
    protocol-shaped object — fakes are trivial).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

import clickhouse_connect
from clickhouse_connect.driver.asyncclient import AsyncClient

from anvil.config import Settings

logger = logging.getLogger(__name__)


class ClickHouseClient(Protocol):
    """The minimal surface the batch inserter / migrations need."""

    async def insert(
        self,
        table: str,
        data: list[tuple[Any, ...]],
        *,
        column_names: Iterable[str],
    ) -> None: ...

    async def command(self, sql: str) -> Any: ...

    async def query(
        self, sql: str, *, parameters: dict[str, Any] | None = None
    ) -> Any: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


@dataclass
class AsyncClickHouseClient:
    """clickhouse-connect adapter implementing the ClickHouseClient protocol.

    The underlying client is created lazily on the first call so a worker
    that boots before ClickHouse is reachable does not crash at import time.
    Reconnect on protocol-level failure is handled by clickhouse-connect's
    internal retry; we just surface the exception to the consumer's retry
    path if it eventually gives up.
    """

    settings: Settings
    _client: AsyncClient | None = None

    async def _ensure(self) -> AsyncClient:
        if self._client is None:
            self._client = await clickhouse_connect.get_async_client(
                host=self.settings.clickhouse_host,
                port=self.settings.clickhouse_port,
                username=self.settings.clickhouse_user,
                password=self.settings.clickhouse_password,
                database=self.settings.clickhouse_database,
                secure=self.settings.clickhouse_secure,
                query_limit=0,
                connect_timeout=10,
                send_receive_timeout=self.settings.clickhouse_query_timeout_seconds,
            )
        return self._client

    async def insert(
        self,
        table: str,
        data: list[tuple[Any, ...]],
        *,
        column_names: Iterable[str],
    ) -> None:
        if not data:
            return
        c = await self._ensure()
        await c.insert(
            table,
            data,
            column_names=list(column_names),
        )

    async def command(self, sql: str) -> Any:
        c = await self._ensure()
        return await c.command(sql)

    async def query(
        self, sql: str, *, parameters: dict[str, Any] | None = None
    ) -> Any:
        c = await self._ensure()
        return await c.query(sql, parameters=parameters)

    async def ping(self) -> bool:
        try:
            c = await self._ensure()
            return await c.ping()
        except Exception:
            logger.exception("clickhouse_ping_failed")
            return False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                logger.exception("clickhouse_close_failed")
            self._client = None


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _render_template(sql: str, *, settings: Settings, filename: str) -> str:
    """Substitute `{retention_days}` for the right per-table value.

    The pattern keeps the DDL declarative — env-driven knobs do not require
    forking the SQL file. Add more placeholders as table TTLs grow.
    """
    if filename.endswith("market_snapshots.sql"):
        return sql.replace("{retention_days}", str(settings.retention_days_market_snapshots))
    if filename.endswith("metric_ticks.sql"):
        return sql.replace("{retention_days}", str(settings.retention_days_metric_ticks))
    if filename.endswith("human_signals.sql"):
        return sql.replace("{retention_days}", str(settings.retention_days_human_signals))
    return sql


def _split_statements(sql: str) -> list[str]:
    """Split a SQL file into individual statements.

    ClickHouse over HTTP wants one statement per command. We split on `;`
    that is at the end of a logical line and strip blank / comment-only
    statements.
    """
    chunks = re.split(r";\s*(?:\r?\n|$)", sql)
    out: list[str] = []
    for chunk in chunks:
        stripped = "\n".join(
            line for line in chunk.splitlines() if not line.strip().startswith("--")
        ).strip()
        if stripped:
            out.append(stripped)
    return out


async def run_migrations(client: ClickHouseClient, settings: Settings) -> list[str]:
    """Apply every `.sql` in `migrations/` in lexicographic order.

    Returns the list of statements that were executed (used in tests).
    Idempotent — every DDL is `CREATE … IF NOT EXISTS`.
    """
    files = sorted(p for p in _MIGRATIONS_DIR.glob("*.sql"))
    executed: list[str] = []
    for path in files:
        raw = path.read_text(encoding="utf-8")
        rendered = _render_template(raw, settings=settings, filename=path.name)
        for stmt in _split_statements(rendered):
            logger.info("applying_migration", extra={"file": path.name})
            await client.command(stmt)
            executed.append(stmt)
    return executed
