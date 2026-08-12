-- EXPLORER-ATLAS-BRIDGE-A — versioned, replay-safe intelligence ingestion.

CREATE TABLE IF NOT EXISTS atlas.explorer_ingestion_batches (
    batch_id             UUID PRIMARY KEY,
    generation_id        TEXT NOT NULL,
    schema_version       VARCHAR(64) NOT NULL,
    source_system        VARCHAR(64) NOT NULL,
    content_hash         VARCHAR(80) NOT NULL UNIQUE,
    status               VARCHAR(24) NOT NULL,
    accepted_records     INTEGER NOT NULL DEFAULT 0,
    rejected_records     INTEGER NOT NULL DEFAULT 0,
    rejection_details    JSONB NOT NULL DEFAULT '[]',
    created_at           TIMESTAMPTZ NOT NULL,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS atlas.explorer_memory_snapshots (
    record_id            UUID PRIMARY KEY,
    batch_id             UUID NOT NULL REFERENCES atlas.explorer_ingestion_batches(batch_id),
    generation_id        TEXT NOT NULL,
    competition          VARCHAR(128) NOT NULL,
    home_team            VARCHAR(128) NOT NULL,
    away_team            VARCHAR(128) NOT NULL,
    observed_at          TIMESTAMPTZ NOT NULL,
    payload               JSONB NOT NULL,
    lineage               JSONB NOT NULL,
    content_hash          VARCHAR(80) NOT NULL UNIQUE,
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_explorer_memory_context
    ON atlas.explorer_memory_snapshots
    (competition, home_team, away_team, observed_at DESC);

CREATE TABLE IF NOT EXISTS atlas.explorer_behavior_observations (
    record_id            UUID PRIMARY KEY,
    batch_id             UUID NOT NULL REFERENCES atlas.explorer_ingestion_batches(batch_id),
    generation_id        TEXT NOT NULL,
    competition          VARCHAR(128) NOT NULL,
    behavior             VARCHAR(96) NOT NULL,
    observed_at          TIMESTAMPTZ NOT NULL,
    payload               JSONB NOT NULL,
    lineage               JSONB NOT NULL,
    content_hash          VARCHAR(80) NOT NULL UNIQUE,
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_explorer_behavior_context
    ON atlas.explorer_behavior_observations
    (competition, behavior, observed_at DESC);

CREATE TABLE IF NOT EXISTS atlas.explorer_signal_observations (
    record_id            UUID PRIMARY KEY,
    batch_id             UUID NOT NULL REFERENCES atlas.explorer_ingestion_batches(batch_id),
    generation_id        TEXT NOT NULL,
    competition          VARCHAR(128) NOT NULL,
    signal_family        VARCHAR(96) NOT NULL,
    observed_at          TIMESTAMPTZ NOT NULL,
    payload               JSONB NOT NULL,
    lineage               JSONB NOT NULL,
    content_hash          VARCHAR(80) NOT NULL UNIQUE,
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_explorer_signal_context
    ON atlas.explorer_signal_observations
    (competition, signal_family, observed_at DESC);

ALTER TABLE atlas.atlas_vector_memory
    ADD COLUMN IF NOT EXISTS source_system VARCHAR(64) NOT NULL DEFAULT 'atlas',
    ADD COLUMN IF NOT EXISTS generation_id TEXT,
    ADD COLUMN IF NOT EXISTS ingest_batch_id UUID,
    ADD COLUMN IF NOT EXISTS lineage JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS ix_atlas_vector_memory_generation
    ON atlas.atlas_vector_memory (generation_id, persisted_at);
