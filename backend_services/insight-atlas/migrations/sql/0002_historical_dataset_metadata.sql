-- ML-0..ML-4 — historical dataset lineage for Atlas model versions.
--
-- Model versions trained from real football history must record the dataset
-- version, temporal window and provider composition that produced them. This
-- migration is additive and keeps existing bootstrap/cold-start versions valid.

ALTER TYPE atlas_family ADD VALUE IF NOT EXISTS 'similarity';

ALTER TABLE atlas.model_versions
    ADD COLUMN IF NOT EXISTS dataset_version VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS historical_window JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS dataset_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
