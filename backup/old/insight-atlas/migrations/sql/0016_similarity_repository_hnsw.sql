-- ATLAS-VECTOR-A — production online vector similarity infrastructure.
--
-- This migration keeps all existing deterministic embeddings valid. New
-- compatibility columns are nullable so historical rows remain queryable by
-- embedding_version while future producers can add stricter schema/catalog
-- filters without a table rebuild.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE atlas.atlas_vector_memory
    ADD COLUMN IF NOT EXISTS feature_schema_version VARCHAR(64),
    ADD COLUMN IF NOT EXISTS signal_catalog_version VARCHAR(64),
    ADD COLUMN IF NOT EXISTS behavior_catalog_version VARCHAR(64),
    ADD COLUMN IF NOT EXISTS season VARCHAR(32),
    ADD COLUMN IF NOT EXISTS market_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS match_phase VARCHAR(64),
    ADD COLUMN IF NOT EXISTS similarity_metadata JSONB NOT NULL DEFAULT '{}';

-- Keep the original metadata lookups, but add a production filter index for
-- online nearest-neighbour queries. The vector index handles the distance
-- ordering; this btree index supports compatibility and domain filters.
CREATE INDEX IF NOT EXISTS ix_atlas_vector_memory_similarity_filters
    ON atlas.atlas_vector_memory (
        embedding_version,
        feature_schema_version,
        signal_catalog_version,
        behavior_catalog_version,
        competition,
        season,
        market_type,
        match_phase,
        created_at
    );

-- Replace the original untuned HNSW index with a production-tuned cosine HNSW
-- index. Existing rows and vector dimensions remain untouched.
DROP INDEX IF EXISTS atlas.ix_atlas_vector_memory_embedding_hnsw;

CREATE INDEX IF NOT EXISTS ix_atlas_vector_memory_embedding_hnsw
    ON atlas.atlas_vector_memory
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
