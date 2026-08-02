-- Sprint 0 (Trend Intelligence Foundation) — durable trend history.
--
-- Every trend the TrendEngine emits is persisted here BEFORE stream
-- publication (persist-then-publish), so the trend timeline is
-- reconstructable and a failed publish on insight:stream:trends is
-- replayable from this table.
--
-- ORM mapping: atlas.registry.models.TrendEventRow. Fresh databases
-- bootstrap via create_all() (sqlite/dev); production runs this
-- migration explicitly.
--
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.trend_events (
    trend_id            UUID             PRIMARY KEY,
    trend_type          VARCHAR(48)      NOT NULL,
    category            VARCHAR(16)      NOT NULL,
    canonical_match_id  UUID             NOT NULL,
    competition_id      UUID             NULL,
    minute              INTEGER          NULL,
    strength            DOUBLE PRECISION NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL,
    direction           INTEGER          NOT NULL DEFAULT 0,
    evidence            JSONB            NOT NULL DEFAULT '{}'::jsonb,
    detected_at         TIMESTAMPTZ      NOT NULL,
    ingested_at         TIMESTAMPTZ      NOT NULL DEFAULT now()
);

-- Per-match trend timeline, optionally filtered by type.
CREATE INDEX IF NOT EXISTS ix_trend_events_match_type
    ON atlas.trend_events (canonical_match_id, trend_type, detected_at);

CREATE INDEX IF NOT EXISTS ix_trend_events_match
    ON atlas.trend_events (canonical_match_id);
CREATE INDEX IF NOT EXISTS ix_trend_events_type
    ON atlas.trend_events (trend_type);
CREATE INDEX IF NOT EXISTS ix_trend_events_detected_at
    ON atlas.trend_events (detected_at);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.trend_events;
-- COMMIT;
