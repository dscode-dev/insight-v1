-- Historical closing odds — one row per (fixture, bookmaker, market).
--
-- Football-Data.co.uk carries six bookmakers plus the market maximum and
-- mean, so a 380-match season produces ~3,000 rows. Five seasons across two
-- competitions is ~30,000 — small for ClickHouse, and the densest signal the
-- platform has about what the market believed before a match.
--
-- WHY IT MATTERS AT RUNTIME. Atlas's job is to say what is happening now, and
-- "unusual" is only definable against a baseline. The consensus price for a
-- home favourite in this competition, the normal dispersion between books,
-- how far a line typically moves — all of it is computed from here. Without
-- it, a live market reading has nothing to be surprised by.
--
-- SELECTIONS ARE COLUMNS, NOT AN ARRAY. The 1X2 market always has home, draw
-- and away, and every question asked of this table compares one of them
-- across matches. An Array(Tuple) would force arrayJoin on every read and
-- make the common query the awkward one. Markets with a variable shape
-- (over/under lines, handicaps) go in `extra_selections` — present so adding
-- them later is not a migration, and empty for 1X2.
--
-- NO TTL. Same reason as historical_fixtures: age is the value.

CREATE TABLE IF NOT EXISTS insight.historical_odds
(
    -- Identity
    external_fixture_id      String,
    source                   LowCardinality(String),
    competition_key          LowCardinality(String),
    season                   LowCardinality(String),
    bookmaker                LowCardinality(String),
    market                   LowCardinality(String),

    -- WHEN THE MARKET SAID IT, not when we downloaded it. Closing odds are
    -- published after the fact; stamping them with the fetch time would put a
    -- 2020 market in 2026 and make any line-movement analysis meaningless.
    captured_at              DateTime64(3, 'UTC'),

    -- Decimal odds. Nullable individually: a book that quoted two of three
    -- outcomes has a partial market, and a 0 there would read as a price.
    home_price               Nullable(Decimal64(6)),
    draw_price               Nullable(Decimal64(6)),
    away_price               Nullable(Decimal64(6)),

    -- Markets whose shape is not 1X2 (totals, handicaps).
    extra_selections         Array(Tuple(String, Decimal64(6), Nullable(Decimal64(4)))),

    -- Provenance
    trust_level              LowCardinality(String),
    confidence               Decimal64(4),

    ingest_ts                DateTime64(3, 'UTC') DEFAULT now64(3),

    INDEX idx_fixture external_fixture_id TYPE bloom_filter GRANULARITY 4
)
ENGINE = ReplacingMergeTree(ingest_ts)
PARTITION BY (competition_key, season)
-- Bookmaker is part of the identity: two books quoting one match are two
-- markets, and collapsing them would destroy the dispersion that makes
-- consensus meaningful.
ORDER BY (competition_key, season, external_fixture_id, market, bookmaker, source)
SETTINGS index_granularity = 8192;
