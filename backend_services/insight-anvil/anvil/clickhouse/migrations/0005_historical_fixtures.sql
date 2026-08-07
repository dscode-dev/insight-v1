-- Historical fixtures — the five-year backfill the Explorer collects.
--
-- WHY THIS IS A SEPARATE TABLE FROM market_snapshots / metric_ticks.
--
-- Those three describe ONE LIVE MATCH being recalculated: they are keyed by
-- `state_version`, the Nth recomputation as the match progresses, and they
-- carry `TTL 90 DAY` because a finished match's intermediate states stop
-- being interesting quickly.
--
-- Historical data is the opposite on every axis. One row per fixture, no
-- versions, and the value is precisely that it is old: a 2020 season is what
-- makes a 2026 similarity lookup mean anything. Writing it into those tables
-- would key it on a version it does not have and delete it after 90 days —
-- the platform would look like it had five years of history right up until
-- the first background merge.
--
-- insight-context.md v2.0 lists BOTH under Anvil ("Dados históricos" next to
-- "Consolidação de eventos"). Two workloads, one service, two shapes.
--
-- NO TTL. Deliberate, and the single most important line here. Adding one
-- later is a decision someone has to make on purpose.
--
-- IDENTITY. `external_fixture_id` is the Explorer's id, which carries its own
-- provenance (`fd-2324-E0-0001` = football-data, 23/24, division E0, row 1).
-- It is a String, not a UUID: the source has no UUID to give, and minting one
-- here would invent an identity nothing else can reproduce. `match_id` is
-- Nullable and stays empty until entity resolution links a historical fixture
-- to a live one — the join that does not exist yet, left visible rather than
-- faked.

CREATE TABLE IF NOT EXISTS insight.historical_fixtures
(
    -- Identity
    external_fixture_id      String,
    source                   LowCardinality(String),
    competition_key          LowCardinality(String),
    season                   LowCardinality(String),
    -- Set once a historical fixture is resolved to a canonical match.
    match_id                 Nullable(UUID),

    -- When
    scheduled_at             DateTime64(3, 'UTC'),

    -- Who
    home_team_name           String,
    away_team_name           String,
    home_club_id             Nullable(String),
    away_club_id             Nullable(String),

    -- Outcome. Nullable because a scheduled fixture has none, and because a
    -- 0 that means "not played" is indistinguishable from a real goalless
    -- draw once it is in a column.
    status                   LowCardinality(String),
    home_score               Nullable(UInt8),
    away_score               Nullable(UInt8),
    halftime_home_score      Nullable(UInt8),
    halftime_away_score      Nullable(UInt8),

    -- Provenance, carried through from the envelope. Confidence and trust
    -- are what let a consumer weigh two sources that disagree instead of
    -- picking whichever arrived last.
    trust_level              LowCardinality(String),
    confidence               Decimal64(4),
    captured_at              DateTime64(3, 'UTC'),

    ingest_ts                DateTime64(3, 'UTC') DEFAULT now64(3),

    INDEX idx_home home_team_name TYPE bloom_filter GRANULARITY 4,
    INDEX idx_away away_team_name TYPE bloom_filter GRANULARITY 4
)
ENGINE = ReplacingMergeTree(ingest_ts)
-- By season, not by month: queries are "this competition, these seasons",
-- and a monthly partition would scan sixty parts to answer one of them.
PARTITION BY (competition_key, season)
-- `source` is in the key so two sources describing the same fixture are two
-- rows, not a silent overwrite. Reconciliation is a read-time decision with
-- confidence in hand; ReplacingMergeTree would make it "last writer wins".
ORDER BY (competition_key, season, external_fixture_id, source)
SETTINGS index_granularity = 8192;
