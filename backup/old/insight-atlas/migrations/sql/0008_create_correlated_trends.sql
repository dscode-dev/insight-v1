-- Sprint 1.5 — correlated trends.
--
-- One row per correlation hit: which member trends co-occurred inside
-- the rule window, with the combined confidence/strength and the full
-- evidence. The fusion trend each correlation also emits lives in
-- atlas.trend_events like any other trend.
--
-- ORM mapping: atlas.registry.models.CorrelatedTrendRow.
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.correlated_trends (
    correlation_id      UUID             PRIMARY KEY,
    canonical_match_id  UUID             NOT NULL,
    correlation_type    VARCHAR(32)      NOT NULL,
    member_trends       JSONB            NOT NULL DEFAULT '[]'::jsonb,
    confidence          DOUBLE PRECISION NOT NULL,
    strength            DOUBLE PRECISION NOT NULL,
    evidence            JSONB            NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ      NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_correlated_trends_match
    ON atlas.correlated_trends (canonical_match_id, created_at);
CREATE INDEX IF NOT EXISTS ix_correlated_trends_type
    ON atlas.correlated_trends (correlation_type);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.correlated_trends;
-- COMMIT;
