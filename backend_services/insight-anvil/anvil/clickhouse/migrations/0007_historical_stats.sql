-- Historical match statistics — one row per (fixture, source).
--
-- Shots, shots on target, corners, fouls, cards. Football-Data carries them
-- in the same CSV as the result, so they arrive for free with every fixture.
--
-- WHY IT MATTERS AT RUNTIME. This is what a live pressure reading is compared
-- against. "Fourteen shots by the 60th minute" is a number; whether it is
-- remarkable depends on what these two teams, in this competition, usually
-- produce — which is a query against this table.
--
-- WIDE COLUMNS, NOT A MAP. Every field here is a known counter that queries
-- average and compare directly. A Map(String, UInt16) would make each of
-- those a lookup and would let a typo become a new statistic nobody notices.
-- Nullable throughout because older seasons omit the stat columns entirely,
-- and 0 shots is a real (if unusual) match — not the same as "not recorded".
--
-- NO TTL.

CREATE TABLE IF NOT EXISTS insight.historical_stats
(
    -- Identity
    external_fixture_id      String,
    source                   LowCardinality(String),
    competition_key          LowCardinality(String),
    season                   LowCardinality(String),

    -- Home
    home_shots               Nullable(UInt16),
    home_shots_on_target     Nullable(UInt16),
    home_corners             Nullable(UInt16),
    home_fouls               Nullable(UInt16),
    home_offsides            Nullable(UInt16),
    home_yellow_cards        Nullable(UInt8),
    home_red_cards           Nullable(UInt8),
    home_possession          Nullable(Decimal64(2)),
    home_expected_goals      Nullable(Decimal64(4)),

    -- Away
    away_shots               Nullable(UInt16),
    away_shots_on_target     Nullable(UInt16),
    away_corners             Nullable(UInt16),
    away_fouls               Nullable(UInt16),
    away_offsides            Nullable(UInt16),
    away_yellow_cards        Nullable(UInt8),
    away_red_cards           Nullable(UInt8),
    away_possession          Nullable(Decimal64(2)),
    away_expected_goals      Nullable(Decimal64(4)),

    -- Provenance
    trust_level              LowCardinality(String),
    confidence               Decimal64(4),
    captured_at              DateTime64(3, 'UTC'),

    ingest_ts                DateTime64(3, 'UTC') DEFAULT now64(3),

    INDEX idx_fixture external_fixture_id TYPE bloom_filter GRANULARITY 4
)
ENGINE = ReplacingMergeTree(ingest_ts)
PARTITION BY (competition_key, season)
ORDER BY (competition_key, season, external_fixture_id, source)
SETTINGS index_granularity = 8192;
