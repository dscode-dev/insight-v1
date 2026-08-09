-- ATLAS-SIM-A — v2 (37-dim) embedding column, coexisting with v1.
--
-- Context: `atlas.atlas_vector_memory.embedding` is `vector(32)` — a
-- FIXED dimension per pgvector column. Growing v1's dimensionality
-- in-place (ALTER COLUMN TYPE vector(37)) would reject/corrupt every
-- existing 32-dim v1 row. Instead, this is a SECOND nullable column
-- with its own HNSW index, selected at read/write time by
-- embedding_version (see atlas/similarity/repository.py,
-- atlas/vector_memory/repository.py) — the exact same additive,
-- non-breaking posture migration 0016 already established for the
-- compatibility filter columns. `embedding` and every existing row are
-- completely untouched by this migration.
--
-- Idempotent: every statement is guarded so re-running on an
-- already-migrated database is a no-op.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE atlas.atlas_vector_memory
    ADD COLUMN IF NOT EXISTS embedding_v2 vector(37);

CREATE INDEX IF NOT EXISTS ix_atlas_vector_memory_embedding_v2_hnsw
    ON atlas.atlas_vector_memory
    USING hnsw (embedding_v2 vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- A v1 row and a v2 row for the SAME match must be able to coexist —
-- one match, two versioned vectors, one row each (v1 rows leave
-- embedding_v2 NULL; v2 rows leave embedding NULL). The original
-- `source_match_id UNIQUE` constraint (migration 0013) only ever
-- assumed one embedding per match and would reject the second row.
-- Every row in this table today is v1-only, so this is a pure
-- constraint swap — no existing data violates the new composite key.
ALTER TABLE atlas.atlas_vector_memory
    DROP CONSTRAINT IF EXISTS atlas_vector_memory_source_match_id_key;

ALTER TABLE atlas.atlas_vector_memory
    ADD CONSTRAINT ux_atlas_vector_memory_match_version
    UNIQUE (source_match_id, embedding_version);

-- Rollback:
--
-- BEGIN;
-- ALTER TABLE atlas.atlas_vector_memory
--     DROP CONSTRAINT IF EXISTS ux_atlas_vector_memory_match_version;
-- ALTER TABLE atlas.atlas_vector_memory
--     ADD CONSTRAINT atlas_vector_memory_source_match_id_key UNIQUE (source_match_id);
-- DROP INDEX IF EXISTS atlas.ix_atlas_vector_memory_embedding_v2_hnsw;
-- ALTER TABLE atlas.atlas_vector_memory DROP COLUMN IF EXISTS embedding_v2;
-- COMMIT;
