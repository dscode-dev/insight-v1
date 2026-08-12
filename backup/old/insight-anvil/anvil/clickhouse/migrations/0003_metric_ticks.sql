-- metric_ticks
--
-- One row per `METRIC_TICK` derived event. Mirrors the flattened structure
-- of MetricTick's `market`, `human`, and `derived` blocks so ML feature
-- queries are single-table column selects with no JSON unpacking.
--
-- Versioning: ReplacingMergeTree(ingest_ts) — same replay-safety model
-- as market_snapshots. ORDER BY puts state_version last so queries that
-- want "feature row at state_version V for this match" are an index seek.

CREATE TABLE IF NOT EXISTS insight.metric_ticks
(
    -- Identity / lineage
    event_id          UUID,
    match_id          UUID,
    region_code       LowCardinality(String),
    market_type       LowCardinality(String),
    state_version     UInt32,
    schema_version    UInt16,
    calc_version      UInt16,
    engine_version    LowCardinality(String),
    correlation_id    Nullable(UUID),
    source            LowCardinality(String),

    -- Watermarks
    ts_event_max      DateTime64(3, 'UTC'),
    ts_ingest         DateTime64(3, 'UTC'),

    -- Quality / flags
    quality           Decimal64(6),
    flags             Array(LowCardinality(String)),

    -- Market features (flattened from MarketFeatures)
    n_bookmakers_total          UInt16,
    n_bookmakers_valid          UInt16,
    consensus_home              Nullable(Decimal64(6)),
    consensus_draw              Nullable(Decimal64(6)),
    consensus_away              Nullable(Decimal64(6)),
    dispersion_home             Nullable(Decimal64(6)),
    dispersion_draw             Nullable(Decimal64(6)),
    dispersion_away             Nullable(Decimal64(6)),
    volatility_home             Decimal64(6),
    volatility_draw             Decimal64(6),
    volatility_away             Decimal64(6),
    liquidity_score             Decimal64(6),
    stability_score             Decimal64(6),
    shock_score                 Decimal64(6),
    market_calc_version         UInt16,

    -- Human features (flattened from HumanFeatures)
    human_quorum                UInt32,
    human_confidence            Decimal64(6),
    human_coordination_score    Decimal64(6),
    human_pressure_home         Decimal64(6),
    human_pressure_away         Decimal64(6),
    human_effort_home           Decimal64(6),
    human_effort_away           Decimal64(6),
    human_ref_pressure          Decimal64(6),
    human_calc_version          UInt16,

    -- Derived metrics (flattened from DerivedMetrics)
    xp_home                     Decimal64(6),
    xp_away                     Decimal64(6),
    xr_home                     Nullable(Decimal64(6)),
    xr_away                     Nullable(Decimal64(6)),
    derived_calc_version        UInt16,

    -- Audit
    ingest_ts                   DateTime64(3, 'UTC') DEFAULT now64(3),

    INDEX idx_event_id          event_id TYPE bloom_filter GRANULARITY 4,
    -- Flags array benefits from a set index for `hasAll`-style filters.
    INDEX idx_flags             flags TYPE set(64) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(ingest_ts)
PARTITION BY toYYYYMM(ts_ingest)
ORDER BY (match_id, market_type, state_version)
TTL toDate(ts_ingest) + INTERVAL {retention_days} DAY
SETTINGS index_granularity = 8192;
