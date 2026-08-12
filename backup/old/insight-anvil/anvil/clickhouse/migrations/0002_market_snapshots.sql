-- market_snapshots
--
-- One row per `MARKET_SNAPSHOT` derived event. The row is a fully flattened
-- projection of the snapshot payload — every outcome (home/draw/away) gets
-- its own set of columns so analytical queries do not need to unnest JSON.
--
-- Engine choice:
--   ReplacingMergeTree(ingest_ts) lets us safely re-ingest the same
--   (match_id, market_type, state_version) tuple — for example after
--   crash-replay in the producer — and keep the most recent insert. Two rows
--   with the same ORDER BY tuple merge into one on background compaction;
--   the row with the larger `ingest_ts` wins. We accept the eventual
--   convergence model: queries that need strict dedup use `FINAL` or
--   `argMax(... , ingest_ts)`.
--
-- Partitioning:
--   By month of `watermark_event_ts` so retention / cold-storage moves can
--   work at partition granularity (DROP PARTITION is cheap; row-by-row
--   delete is not).
--
-- ORDER BY:
--   (match_id, market_type, state_version) — the natural backtesting axis
--   ("what did the market look like at state_version V for this match").
--   Including state_version in the sort key means as-of queries are an
--   index seek, not a scan.
--
-- TTL:
--   90 days by default. The placeholder `{retention_days}` is templated at
--   migration time (anvil.clickhouse.client._render_template) so different
--   environments can stretch or shrink the window without forking the DDL.

CREATE TABLE IF NOT EXISTS insight.market_snapshots
(
    -- Identity / lineage
    event_id            UUID,
    snapshot_id         UUID,
    match_id            UUID,
    region_code         LowCardinality(String),
    market_type         LowCardinality(String),
    state_version       UInt32,
    calc_version        UInt16,
    engine_version      LowCardinality(String),

    -- Watermarks. event_ts is the upstream timestamp, ingest_ts is when
    -- the producer saw the source tick. Both are needed for replay safety
    -- and lag analysis.
    watermark_event_ts  DateTime64(3, 'UTC'),
    watermark_ingest_ts DateTime64(3, 'UTC'),
    generated_at        DateTime64(3, 'UTC'),

    -- Per-outcome aggregates. Decimal64(6) is wide enough for any plausible
    -- odd (max ~10000) at 6 decimal places of precision. Nullable so a
    -- partial snapshot (e.g. away leg not yet seen) is representable.
    home_best_odd            Nullable(Decimal64(6)),
    home_best_bookmaker_id   Nullable(UUID),
    home_consensus_odd       Nullable(Decimal64(6)),
    home_dispersion          Nullable(Decimal64(6)),
    home_sample_size         Nullable(UInt16),

    draw_best_odd            Nullable(Decimal64(6)),
    draw_best_bookmaker_id   Nullable(UUID),
    draw_consensus_odd       Nullable(Decimal64(6)),
    draw_dispersion          Nullable(Decimal64(6)),
    draw_sample_size         Nullable(UInt16),

    away_best_odd            Nullable(Decimal64(6)),
    away_best_bookmaker_id   Nullable(UUID),
    away_consensus_odd       Nullable(Decimal64(6)),
    away_dispersion          Nullable(Decimal64(6)),
    away_sample_size         Nullable(UInt16),

    n_bookmakers_total       UInt16,
    n_bookmakers_valid       UInt16,

    -- Audit
    ingest_ts                DateTime64(3, 'UTC') DEFAULT now64(3),

    INDEX idx_event_id event_id TYPE bloom_filter GRANULARITY 4
)
ENGINE = ReplacingMergeTree(ingest_ts)
PARTITION BY toYYYYMM(watermark_event_ts)
ORDER BY (match_id, market_type, state_version)
TTL toDate(watermark_event_ts) + INTERVAL {retention_days} DAY
SETTINGS index_granularity = 8192;
