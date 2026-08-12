-- Sprint 1.5 — Trend Contract V2 evaluation fields on atlas.trend_events.
--
-- Persists the publish-score evaluation alongside each trend so the
-- stored record is the COMPLETE audit trail: what was detected, what
-- lifecycle state it was in, which correlations it joined, what score
-- it earned and which publication tier resulted. Strictly additive —
-- no v1 column is altered or removed.
--
-- ORM mapping: atlas.registry.models.TrendEventRow.
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

ALTER TABLE atlas.trend_events
    ADD COLUMN IF NOT EXISTS publish_score    DOUBLE PRECISION NULL,
    ADD COLUMN IF NOT EXISTS publication_tier VARCHAR(20)      NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS lifecycle_state  VARCHAR(16)      NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS correlation_ids  JSONB            NOT NULL DEFAULT '[]'::jsonb;

-- Consumer-side filters: "everything that actually published".
CREATE INDEX IF NOT EXISTS ix_trend_events_tier
    ON atlas.trend_events (publication_tier);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP INDEX IF EXISTS atlas.ix_trend_events_tier;
-- ALTER TABLE atlas.trend_events
--     DROP COLUMN IF EXISTS publish_score,
--     DROP COLUMN IF EXISTS publication_tier,
--     DROP COLUMN IF EXISTS lifecycle_state,
--     DROP COLUMN IF EXISTS correlation_ids;
-- COMMIT;
