-- ATLAS-VECTOR-A — deterministic vector memory.
--
-- Vector memory complements hierarchical football memory. Identity and
-- competition filters remain mandatory before vector distance is evaluated.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS atlas.atlas_vector_memory (
    vector_id              UUID PRIMARY KEY,
    source_match_id        TEXT NOT NULL UNIQUE,
    competition            VARCHAR(128) NOT NULL,
    regime                 VARCHAR(32) NOT NULL,
    home_team              VARCHAR(128) NOT NULL,
    away_team              VARCHAR(128) NOT NULL,
    behavior               JSONB NOT NULL DEFAULT '[]',
    trends                  JSONB NOT NULL DEFAULT '[]',
    signals                 JSONB NOT NULL DEFAULT '[]',
    market_available        BOOLEAN NOT NULL DEFAULT FALSE,
    uncertainty             DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    embedding_version       VARCHAR(32) NOT NULL,
    embedding               vector(32) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL,
    persisted_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_atlas_vector_memory_competition_regime
    ON atlas.atlas_vector_memory (competition, regime, created_at);

CREATE INDEX IF NOT EXISTS ix_atlas_vector_memory_home_team
    ON atlas.atlas_vector_memory (home_team, created_at);

CREATE INDEX IF NOT EXISTS ix_atlas_vector_memory_away_team
    ON atlas.atlas_vector_memory (away_team, created_at);

CREATE INDEX IF NOT EXISTS ix_atlas_vector_memory_embedding_hnsw
    ON atlas.atlas_vector_memory
    USING hnsw (embedding vector_cosine_ops);

