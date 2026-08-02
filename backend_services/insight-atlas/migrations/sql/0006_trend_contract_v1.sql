-- Sprint 1 — Trend Contract V1 columns on atlas.trend_events.
--
-- Adds the public-contract fields (agent, severity, title, summary,
-- signals, chart_data) so the persisted trend history is a full
-- Contract V1 record, replayable onto insight:stream:trends without
-- re-deriving text or chart series.
--
-- ORM mapping: atlas.registry.models.TrendEventRow.
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

ALTER TABLE atlas.trend_events
    ADD COLUMN IF NOT EXISTS agent      VARCHAR(24)   NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS severity   VARCHAR(12)   NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS title      VARCHAR(256)  NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS summary    VARCHAR(1024) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS signals    JSONB         NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS chart_data JSONB         NOT NULL DEFAULT '{}'::jsonb;

-- Severity is a primary consumer filter ("only high/critical trends").
CREATE INDEX IF NOT EXISTS ix_trend_events_severity
    ON atlas.trend_events (severity);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP INDEX IF EXISTS atlas.ix_trend_events_severity;
-- ALTER TABLE atlas.trend_events
--     DROP COLUMN IF EXISTS agent,
--     DROP COLUMN IF EXISTS severity,
--     DROP COLUMN IF EXISTS title,
--     DROP COLUMN IF EXISTS summary,
--     DROP COLUMN IF EXISTS signals,
--     DROP COLUMN IF EXISTS chart_data;
-- COMMIT;
