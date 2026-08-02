-- Sprint 0 — add label_source enum + column to atlas.model_versions.
--
-- Context: Sprint 0 mandates "clear separation between candidate bot
-- signals and confirmed events". The same rule applies to LABELS used
-- in training. bootstrap_labels() in atlas/models/classifier.py
-- generates labels from a deterministic rule — models trained that
-- way are essentially the rule with XGBoost noise. The operator
-- promoting a version must see this distinction.
--
-- Atlas bootstraps schema via SQLAlchemy `Base.metadata.create_all()`
-- (see atlas/api/app.py). On a FRESH database, the column is created
-- automatically from the updated ModelVersion mapping. On an EXISTING
-- deployment, run this migration manually before the new code rolls
-- (the column has a default, so the new code is forward-compatible
-- with the old schema for one release window — but values default to
-- 'none' which is misleading for classifier/ranker, hence: run it).
--
-- Idempotent: re-running on an already-migrated DB is a no-op.

BEGIN;

-- 1. Enum type (idempotent via DO block — Postgres CREATE TYPE has no
--    IF NOT EXISTS as of v16).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type WHERE typname = 'atlas_label_source'
    ) THEN
        CREATE TYPE atlas_label_source AS ENUM (
            'none',
            'bootstrap_rule',
            'historical_outcome',
            'human_curated'
        );
    END IF;
END
$$;

-- 2. Column add (idempotent via IF NOT EXISTS).
ALTER TABLE atlas.model_versions
    ADD COLUMN IF NOT EXISTS label_source atlas_label_source
        NOT NULL DEFAULT 'none';

-- 3. Backfill: any existing classifier/ranker rows are very likely
--    bootstrap-rule trained (that's the only path the codebase had
--    before this migration). Mark them so operators see the lineage
--    correctly on /v1/meta/models.
UPDATE atlas.model_versions
   SET label_source = 'bootstrap_rule'
 WHERE family IN ('classifier', 'ranker')
   AND label_source = 'none';

COMMIT;

-- Rollback:
--
-- BEGIN;
-- ALTER TABLE atlas.model_versions DROP COLUMN IF EXISTS label_source;
-- DROP TYPE IF EXISTS atlas_label_source;
-- COMMIT;
