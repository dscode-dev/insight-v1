-- Sprint 2 — Atlas finalization (Contract V3 + timeline + patterns).
--
-- 1. trend_lifecycle.state_history — ordered list of every state the
--    instance entered (the trend timeline consumers read).
-- 2. trend_events meaning columns — the interpretation layer's output
--    persisted alongside each trend (auditable Contract V3).
-- 3. atlas.pattern_memory — statistical recurrence counters per
--    (competition, trend_type, direction) behaviour.
--
-- ORM mappings: TrendLifecycleRow, TrendEventRow, PatternMemoryRow.
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

ALTER TABLE atlas.trend_lifecycle
    ADD COLUMN IF NOT EXISTS state_history JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE atlas.trend_events
    ADD COLUMN IF NOT EXISTS meaning            VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS meaning_category   VARCHAR(32) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS meaning_confidence DOUBLE PRECISION NULL;

CREATE TABLE IF NOT EXISTS atlas.pattern_memory (
    pattern_id      VARCHAR(128) PRIMARY KEY,
    competition_id  UUID         NULL,
    trend_type      VARCHAR(48)  NOT NULL,
    direction       INTEGER      NOT NULL DEFAULT 0,
    occurrences     INTEGER      NOT NULL DEFAULT 0,
    confirmed       INTEGER      NOT NULL DEFAULT 0,
    failed          INTEGER      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pattern_memory_competition
    ON atlas.pattern_memory (competition_id);
CREATE INDEX IF NOT EXISTS ix_pattern_memory_type
    ON atlas.pattern_memory (trend_type);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.pattern_memory;
-- ALTER TABLE atlas.trend_events
--     DROP COLUMN IF EXISTS meaning,
--     DROP COLUMN IF EXISTS meaning_category,
--     DROP COLUMN IF EXISTS meaning_confidence;
-- ALTER TABLE atlas.trend_lifecycle DROP COLUMN IF EXISTS state_history;
-- COMMIT;
