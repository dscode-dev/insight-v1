-- Let a v2-only row exist — finishing what 0018 declared.
--
-- Migration 0018 added `embedding_v2 vector(37)` next to `embedding
-- vector(32)` and swapped the unique key to (source_match_id,
-- embedding_version), so one match can hold one v1 row and one v2 row. Its
-- own comment states the shape:
--
--     "v1 rows leave embedding_v2 NULL; v2 rows leave embedding NULL"
--
-- The first half worked, because `embedding_v2` was added nullable. The
-- second never could: `embedding` has been NOT NULL since migration 0013,
-- and 0018 did not relax it. So `PgVectorMemoryRepository.upsert_many_v2`
-- — which deliberately does not write `embedding`, because a v2 row has no
-- 32-dim vector — could not insert a single row:
--
--     asyncpg.exceptions.NotNullViolationError:
--     null value in column "embedding" violates not-null constraint
--
-- It went unnoticed because nothing had ever run the v2 backfill against a
-- real database. The table was empty, the tests use their own fixtures, and
-- the constraint only fires on a real INSERT.
--
-- WHY NULLABLE RATHER THAN A DEFAULT. A zero vector is not "no vector": it
-- is a point in the space, at distance from everything, and cosine
-- similarity against it is undefined (zero magnitude). A v2 row genuinely
-- has no v1 embedding, and NULL is the only value that says so. Every read
-- path already filters by embedding_version, so no query sees the NULL.
--
-- Idempotent.

ALTER TABLE atlas.atlas_vector_memory
    ALTER COLUMN embedding DROP NOT NULL;

-- Both columns being NULL would be a row that encodes nothing — accepted by
-- the types, meaningless to every consumer, and invisible to a search that
-- filters by version. The constraint makes that unrepresentable rather than
-- merely unlikely.
ALTER TABLE atlas.atlas_vector_memory
    DROP CONSTRAINT IF EXISTS ck_atlas_vector_memory_has_embedding;

ALTER TABLE atlas.atlas_vector_memory
    ADD CONSTRAINT ck_atlas_vector_memory_has_embedding
    CHECK (embedding IS NOT NULL OR embedding_v2 IS NOT NULL);

-- Rollback:
--
-- BEGIN;
-- ALTER TABLE atlas.atlas_vector_memory
--     DROP CONSTRAINT IF EXISTS ck_atlas_vector_memory_has_embedding;
-- -- Only possible once every v2-only row is removed:
-- --   DELETE FROM atlas.atlas_vector_memory WHERE embedding IS NULL;
-- ALTER TABLE atlas.atlas_vector_memory
--     ALTER COLUMN embedding SET NOT NULL;
-- COMMIT;
