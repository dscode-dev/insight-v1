-- Sprint 6.1 — production table for the first-class odds-history dataset.
--
-- Context: Atlas consumes `match.odds` canonical events off
-- insight:stream:events:odds and appends EVERY snapshot here (we do NOT
-- keep only the latest). The full temporal evolution of each
-- (match, market, bookmaker) lane is reconstructable by ordering on
-- captured_at. The matching ORM mapping is atlas.registry.models.OddsTickRow.
--
-- On a FRESH database Atlas can bootstrap the table via
-- Base.metadata.create_all() (sqlite/dev). In PRODUCTION run this
-- migration explicitly — do NOT rely on auto-create.
--
-- Idempotent: every statement is guarded so re-running on an
-- already-migrated database is a no-op.

BEGIN;

-- Schema (Atlas owns the `atlas` namespace; shared with model_versions).
CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.odds_ticks (
    id                  UUID            PRIMARY KEY,
    -- The Hub's canonical event id — the idempotency key. A re-delivered
    -- canonical event (consumer reclaim/replay) is a no-op insert, so
    -- history never double-counts a snapshot.
    canonical_event_id  UUID            NOT NULL,
    provider            VARCHAR(64)     NOT NULL DEFAULT '',
    competition_id      UUID            NULL,
    -- Stable per-match grouping key (payload.match_id), NOT the
    -- snapshot-scoped canonical match_id.
    match_id            UUID            NOT NULL,
    market              VARCHAR(32)     NOT NULL,
    bookmaker           VARCHAR(64)     NOT NULL,
    -- h2h convenience projections (NULL for non-h2h markets).
    home                DOUBLE PRECISION NULL,
    draw                DOUBLE PRECISION NULL,
    away                DOUBLE PRECISION NULL,
    captured_at         TIMESTAMPTZ     NOT NULL,
    -- Full normalized payload — outcomes[] is the source of truth and is
    -- preserved here for every market (over_under, asian_handicap, btts,
    -- corners, cards, …), not just the h2h projections.
    payload             JSONB           NOT NULL DEFAULT '{}'::jsonb,
    ingested_at         TIMESTAMPTZ     NOT NULL DEFAULT now()
);

-- Idempotency: one row per canonical event.
CREATE UNIQUE INDEX IF NOT EXISTS ux_odds_ticks_canonical_event_id
    ON atlas.odds_ticks (canonical_event_id);

-- History reconstruction: per-match timeline, optionally per market.
CREATE INDEX IF NOT EXISTS ix_odds_ticks_match_market_captured
    ON atlas.odds_ticks (match_id, market, captured_at);

-- Match-scoped scans + time-range reads.
CREATE INDEX IF NOT EXISTS ix_odds_ticks_match_id
    ON atlas.odds_ticks (match_id);
CREATE INDEX IF NOT EXISTS ix_odds_ticks_captured_at
    ON atlas.odds_ticks (captured_at);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.odds_ticks;
-- COMMIT;
