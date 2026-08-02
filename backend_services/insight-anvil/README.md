# Anvil

**Insight Layer F/E** — analytics worker. Consumes the **derived events**
that Atlas emits and persists them to **ClickHouse** as wide,
queryable, ML-ready rows.

```
   Atlas                         Anvil               ClickHouse
   ─────                         ─────               ──────────
   insight:stream:derived:p* ─►  consumer  ─batch─►  insight.market_snapshots
                                  + handler           insight.metric_ticks
                                  + inserter          insight.human_signals (reserved)
```

## Why this exists

Atlas's hot path is for *real-time* intelligence — it writes match state
back to Redis and emits derived events on every recalculation. Those derived
events are a perfect feed for the *historical* analytics layer:

* **Backtesting** — "what did the consensus odds look like at state_version
  V of match M?" is an index seek into `market_snapshots`.
* **ML feature retrieval** — `metric_ticks` is a wide table where every
  feature in `MarketFeatures`, `HumanFeatures`, and `DerivedMetrics` is its
  own column. No JSON unpacking in feature pipelines.
* **Operational forensics** — replay analysis, retention audits, lineage.

## Architecture

```
   ┌─────────────────────────────────────────────────────────────┐
   │ Anvil worker (1..N pods, Redis consumer group)              │
   │                                                             │
   │  ┌──────────────────────┐    ┌──────────────────────────┐   │
   │  │ MultiStreamConsumer  │ ─▶ │ DerivedEventHandler      │   │
   │  │ (anvil.streaming)    │    │  · dispatch by event_type│   │
   │  │                      │    │  · map payload → row     │   │
   │  └──────────────────────┘    └──────────────────────────┘   │
   │             ▲                              │                │
   │             │                              ▼                │
   │   /live /ready /metrics            ┌────────────────────┐   │
   │   (anvil.runtime HealthServer)     │ BatchInserter      │   │
   │                                    │  · per-table buffer│   │
   │                                    │  · size + age flush│   │
   │                                    │  · retry-on-error  │   │
   │                                    │    (rows restored) │   │
   │                                    └────────────────────┘   │
   │                                              │              │
   │                                              ▼              │
   │                                    ┌────────────────────┐   │
   │                                    │ AsyncClickHouseClient  │
   │                                    │  · clickhouse-connect  │
   │                                    │  · migration runner │   │
   │                                    └────────────────────┘   │
   └─────────────────────────────────────────────────────────────┘
```

### Runtime + streaming (Anvil-owned)

The hardened streaming/runtime surfaces are part of Anvil itself —
absorbed during the Consolidation Sprint so the analytics worker
depends on no other service's package:

| Module | Why |
|---|---|
| `anvil.streaming.consumer_multi` | Hardened multi-stream consumer (graceful shutdown, retry/backoff, DLQ, payload bounds, BUSYGROUP discrimination, structured tracing). |
| `anvil.runtime.logging` | JSON-structured logging with `extra={}` surfaced as fields. |
| `anvil.runtime.tracing` | OTel `span()` wrapper — env-driven exporter, no-op safe. |
| `anvil.runtime.health` | `/live`, `/ready`, `/metrics` HTTP server. |
| `anvil.runtime.redis_factory` | Async Redis client + connection pool (Anvil settings). |
| `anvil.runtime.consumer_metrics` | Consumer-loop Prometheus metrics (`anvil_*` prefix). |

### What Anvil owns

| Module | Purpose |
|---|---|
| `anvil.config.settings` | `Settings` (pydantic-settings) + `get_settings()` cached factory. |
| `anvil.clickhouse.client` | `AsyncClickHouseClient` (lazily-connected wrapper around `clickhouse-connect`), `run_migrations()`. |
| `anvil.clickhouse.migrations/*.sql` | Idempotent DDL (`CREATE … IF NOT EXISTS`) with `{retention_days}` templating per table. |
| `anvil.clickhouse.schemas` | Column-order constants — the inserter binds tuples positionally to these. |
| `anvil.mappers` | DerivedEvent payload → column-ordered tuple. Hand-written, fast, no reflection. |
| `anvil.batch.inserter` | Buffered insert with size + age triggers, restore-on-failure, column-shape drift detection. |
| `anvil.handlers.derived_handler` | Dispatch table from `event_type` to mapper + buffer. Unsupported types are skipped, not raised. |
| `anvil.runtime.metrics` | Anvil-specific Prometheus counters/histograms (analytics throughput + CH insert latency). |
| `anvil.worker.anvil_worker` | Entrypoint: settings → migrations → consumer → handler → inserter → graceful shutdown. |

## ClickHouse schema design

Three tables in `insight.*`:

### `market_snapshots`

One row per `MARKET_SNAPSHOT` derived event. Every outcome
(`home`/`draw`/`away`) is flattened into its own group of columns so
analytical queries are pure column selects — no `JSONExtract`, no `arrayJoin`.

* **Engine**: `ReplacingMergeTree(ingest_ts)` — replay-safe; the same
  `(match_id, market_type, state_version)` tuple inserted twice converges
  to one row on background merge.
* **Partitioning**: `toYYYYMM(watermark_event_ts)` — monthly partitions
  enable cheap retention via `DROP PARTITION`.
* **ORDER BY**: `(match_id, market_type, state_version)` — backtesting
  "as-of state_version V" is an index seek.
* **TTL**: `toDate(watermark_event_ts) + INTERVAL {retention_days} DAY`
  (default 90).

### `metric_ticks`

One row per `METRIC_TICK`. Mirrors the flattened structure of MetricTick's
`market`, `human`, and `derived` blocks — ~30 feature columns ready for
ML pipelines without any unnesting.

Same engine, partitioning, and ORDER BY strategy as `market_snapshots`.
TTL default also 90 days.

### `human_signals` (reserved)

Placeholder for the future `HUMAN_SIGNAL` event type the Social Domain
will emit. Empty today; the migration creates the table so dashboards
and JOINs against it don't need special-casing for absence.

## Backtesting query patterns

```sql
-- Snapshot as of state_version V for match M
SELECT * FROM insight.market_snapshots FINAL
WHERE  match_id = {match_id:UUID}
  AND  market_type = 'FT_1X2'
  AND  state_version <= {as_of:UInt32}
ORDER BY state_version DESC
LIMIT 1;

-- All consensus_home moves in a match
SELECT state_version, watermark_event_ts, home_consensus_odd
FROM   insight.market_snapshots FINAL
WHERE  match_id = {match_id:UUID}
ORDER BY state_version;

-- Latest metric tick per (match, market) — useful for ML feature store
SELECT argMax(metric_ticks, ts_ingest) AS latest
FROM   insight.metric_ticks
GROUP BY match_id, market_type;
```

`FINAL` is fine for ad-hoc analyses; the production query layer (Layer A /
gateway, not yet built) should rewrite to `argMax(... , ingest_ts)` for
hot dashboards because `FINAL` is read-amplified.

## Run

```bash
poetry install
REDIS_URL=redis://localhost:6379/0 \
CLICKHOUSE_HOST=localhost \
CLICKHOUSE_DATABASE=insight \
poetry run python -m anvil.worker.anvil_worker
```

The worker:
1. Configures structured logging + OTel tracing (env-driven).
2. Applies migrations (`AUTO_APPLY_MIGRATIONS=false` to skip).
3. Pings ClickHouse + Redis on `/ready`.
4. Consumes `insight:stream:derived:p0..pN`.
5. Maps + buffers + flushes to ClickHouse.

## Tests

```bash
poetry run pytest -q
```

Coverage:
- `test_market_snapshot_mapper.py` — payload round-trip + column positions.
- `test_metric_tick_mapper.py` — same for `MetricTick`.
- `test_batch_inserter.py` — per-table cap, total max, age trigger,
  restore-on-failure, column-shape drift.
- `test_derived_handler.py` — dispatch by event_type, skip unknowns,
  raise on invalid payload.
- `test_migrations.py` — every `.sql` is executed in order; `{retention_days}`
  is rendered per table; comments are stripped.
