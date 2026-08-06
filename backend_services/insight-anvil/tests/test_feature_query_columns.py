"""Every column the feature queries name must exist in the table's DDL.

The market half of the feature snapshot queried `market_snapshots
.ts_ingest`, a column that table never had — the DDL calls it
`watermark_ingest_ts`. ClickHouse answered UNKNOWN_IDENTIFIER, Anvil
turned that into a 500, and Atlas surfaced it as a degraded snapshot.
The mistake looked plausible because `metric_ticks` and `human_signals`
really do have `ts_ingest`.

Nothing caught it: the query only runs against a real ClickHouse with a
real schema, and the service's own tests stub the client. Parsing the
DDL and the SQL is what makes the mismatch visible without a database.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ANVIL = Path(__file__).resolve().parents[1] / "anvil"
_MIGRATIONS = _ANVIL / "clickhouse" / "migrations"
_SERVICE = _ANVIL / "features" / "service.py"

# Identifiers that appear in the SQL but are not table columns.
_NOT_COLUMNS = {
    "select", "from", "where", "and", "or", "as", "order", "by", "desc",
    "asc", "limit", "interval", "second", "count", "avg", "stddevpop",
    "anylast", "any", "min", "max", "sum", "null", "not", "is",
}


def _columns_by_table() -> dict[str, set[str]]:
    """Column names per table, read from the CREATE TABLE statements."""
    tables: dict[str, set[str]] = {}
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
            r"(?:[\w{}$]+\.)?(\w+)\s*\((.*?)\)\s*ENGINE",
            sql,
            re.S | re.I,
        ):
            table, body = match.group(1), match.group(2)
            columns = tables.setdefault(table, set())
            for line in body.splitlines():
                line = line.strip()
                if not line or line.startswith("--"):
                    continue
                name = re.match(r"(\w+)\s+\w", line)
                if name:
                    columns.add(name.group(1).lower())
    return tables


def _queries() -> list[tuple[str, str]]:
    """(table, sql) for each SELECT in the feature service."""
    source = _SERVICE.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    for block in re.findall(r'"""(\s*SELECT.*?)"""', source, re.S | re.I):
        table = re.search(r"FROM\s+(\w+)", block, re.I)
        if table:
            out.append((table.group(1).lower(), block))
    return out


def test_the_ddl_and_the_queries_were_both_found():
    # A parser that silently matches nothing would make every assertion
    # below vacuously pass.
    tables = _columns_by_table()
    assert {"market_snapshots", "metric_ticks", "human_signals"} <= set(tables)
    # Four queries: pressure, market, signals, series. The `minute`
    # query was removed — the column it read does not exist in the
    # schema (see features/service.py).
    assert len(_queries()) == 4


@pytest.mark.parametrize(
    ("table", "sql"),
    _queries(),
    ids=[f"{t}-{i}" for i, (t, _) in enumerate(_queries())],
)
def test_query_only_references_real_columns(table: str, sql: str) -> None:
    columns = _columns_by_table().get(table)
    assert columns, f"no DDL found for table {table}"

    # Placeholders are `{name:Type}` — strip them so the parameter names
    # are not mistaken for columns.
    stripped = re.sub(r"\{[^}]*\}", " ", sql)
    referenced = {
        token.lower()
        for token in re.findall(r"\b[a-z_][a-z0-9_]*\b", stripped, re.I)
        if token.lower() not in _NOT_COLUMNS
    }
    # Aliases introduced by `AS x` are outputs, not columns.
    referenced -= {a.lower() for a in re.findall(r"\bAS\s+(\w+)", sql, re.I)}
    referenced.discard(table)

    unknown = sorted(referenced - columns)
    assert not unknown, (
        f"{table} query references column(s) that do not exist in its DDL: "
        f"{unknown}. Available: {sorted(columns)}"
    )


def test_market_snapshots_has_no_ts_ingest_column():
    # Pins the specific trap: the name reads as correct because two
    # sibling tables do have it.
    columns = _columns_by_table()["market_snapshots"]
    assert "ts_ingest" not in columns
    assert "watermark_ingest_ts" in columns
    assert "ts_ingest" in _columns_by_table()["metric_ticks"]
    assert "ts_ingest" in _columns_by_table()["human_signals"]


def test_no_alias_shadows_the_column_it_reads():
    """`SELECT anyLast(x) AS x` is a circular reference for ClickHouse 24.8.

    Its analyzer resolves the alias before the column, so the expression
    refers to itself and the query dies with UNKNOWN_IDENTIFIER — while
    unhelpfully suggesting "Maybe you meant: ['minute']". This shape is
    accepted by older ClickHouse, so it only breaks on upgrade, and it
    breaks the whole feature snapshot rather than one field.
    """
    tables = _columns_by_table()
    offenders: list[str] = []
    for table, sql in _queries():
        columns = tables.get(table, set())
        for expression, alias in re.findall(
            r"(\w+)\s*\(\s*(\w+)\s*\)\s+AS\s+\2\b", sql, re.I
        ):
            if alias.lower() in columns:
                offenders.append(f"{table}: {expression}({alias}) AS {alias}")
    assert not offenders, "alias shadows its own column: " + "; ".join(offenders)
