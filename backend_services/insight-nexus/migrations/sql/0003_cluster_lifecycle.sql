-- Nexus Sprint 3.5 — cluster lifecycle.
--
-- Narratives become finite: clusters carry a lifecycle state
-- (ACTIVE/COMPLETED/FAILED/EXPIRED), opened/closed timestamps and an
-- auditable close_reason. The (match_id, cluster_type) UNIQUE
-- constraint is replaced by a partial unique index over ACTIVE rows
-- only, so a closed story can be FOLLOWED by a fresh cluster of the
-- same type on the same match (reopen behaviour — old clusters are
-- never reused).
--
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

ALTER TABLE nexus.trend_clusters
    ADD COLUMN IF NOT EXISTS state        VARCHAR(12) NOT NULL DEFAULT 'ACTIVE',
    ADD COLUMN IF NOT EXISTS opened_at    TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS closed_at    TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS close_reason VARCHAR(48) NOT NULL DEFAULT '';

-- Backfill opened_at from created_at for pre-3.5 rows.
UPDATE nexus.trend_clusters SET opened_at = created_at WHERE opened_at IS NULL;
ALTER TABLE nexus.trend_clusters ALTER COLUMN opened_at SET NOT NULL;

-- Replace the hard uniqueness with ACTIVE-only uniqueness.
ALTER TABLE nexus.trend_clusters
    DROP CONSTRAINT IF EXISTS trend_clusters_match_id_cluster_type_key;
CREATE UNIQUE INDEX IF NOT EXISTS ux_trend_clusters_active
    ON nexus.trend_clusters (match_id, cluster_type)
    WHERE state = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_trend_clusters_state
    ON nexus.trend_clusters (state);
CREATE INDEX IF NOT EXISTS ix_trend_clusters_match_state
    ON nexus.trend_clusters (match_id, state);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP INDEX IF EXISTS nexus.ux_trend_clusters_active;
-- DROP INDEX IF EXISTS nexus.ix_trend_clusters_state;
-- DROP INDEX IF EXISTS nexus.ix_trend_clusters_match_state;
-- ALTER TABLE nexus.trend_clusters
--     DROP COLUMN IF EXISTS state,
--     DROP COLUMN IF EXISTS opened_at,
--     DROP COLUMN IF EXISTS closed_at,
--     DROP COLUMN IF EXISTS close_reason;
-- COMMIT;
