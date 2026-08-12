-- Sprint 1.5 — trend lifecycle state machine.
--
-- One row per TrendInstance: how a detected pattern strengthened,
-- weakened, confirmed, failed or expired over time. trend_events rows
-- remain immutable; the lifecycle is a separate record keyed by
-- instance_id with full parallel histories (JSONB) so every state
-- transition is reproducible from stored evidence.
--
-- ORM mapping: atlas.registry.models.TrendLifecycleRow.
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.trend_lifecycle (
    instance_id         UUID         PRIMARY KEY,
    canonical_match_id  UUID         NOT NULL,
    trend_type          VARCHAR(48)  NOT NULL,
    direction           INTEGER      NOT NULL DEFAULT 0,
    current_state       VARCHAR(16)  NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL,
    last_seen_at        TIMESTAMPTZ  NOT NULL,
    trend_ids           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    strength_history    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    confidence_history  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    evidence_history    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    confirmed_by        VARCHAR(64)  NULL,
    failed_by           VARCHAR(64)  NULL
);

-- The hot lookup: open instances for one match.
CREATE INDEX IF NOT EXISTS ix_trend_lifecycle_match_state
    ON atlas.trend_lifecycle (canonical_match_id, current_state);
CREATE INDEX IF NOT EXISTS ix_trend_lifecycle_match
    ON atlas.trend_lifecycle (canonical_match_id);
CREATE INDEX IF NOT EXISTS ix_trend_lifecycle_type
    ON atlas.trend_lifecycle (trend_type);
CREATE INDEX IF NOT EXISTS ix_trend_lifecycle_state
    ON atlas.trend_lifecycle (current_state);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.trend_lifecycle;
-- COMMIT;
