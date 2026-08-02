-- human_signals
--
-- Placeholder for the HUMAN_SIGNAL derived event type. The backend does not
-- emit these yet (Layer B / Social Domain is still ahead of us in the V1
-- roadmap), but reserving the table now means:
--   * the schema migration runner has a stable target,
--   * the mapper / handler dispatch table can stay symmetric across event
--     kinds, and
--   * dashboards and backtests can JOIN against an empty table without
--     special-casing absence.
--
-- Retention defaults longer than market/metric tables because human signals
-- are the more valuable long-term ML feature.

CREATE TABLE IF NOT EXISTS insight.human_signals
(
    event_id          UUID,
    match_id          UUID,
    user_id           UUID,
    region_code       LowCardinality(String),
    signal_type       LowCardinality(String),

    ts_event          DateTime64(3, 'UTC'),
    ts_ingest         DateTime64(3, 'UTC'),
    minute            Nullable(Int16),

    value             Decimal64(6),
    weight            Decimal64(6),
    reputation_score  Decimal64(6),
    abuse_decision    LowCardinality(String),
    weight_multiplier Decimal64(6),

    ingest_ts         DateTime64(3, 'UTC') DEFAULT now64(3),

    INDEX idx_event_id event_id TYPE bloom_filter GRANULARITY 4
)
ENGINE = ReplacingMergeTree(ingest_ts)
PARTITION BY toYYYYMM(ts_event)
ORDER BY (match_id, signal_type, ts_event, event_id)
TTL toDate(ts_event) + INTERVAL {retention_days} DAY
SETTINGS index_granularity = 8192;
