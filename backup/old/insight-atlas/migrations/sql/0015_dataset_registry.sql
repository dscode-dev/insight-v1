CREATE TABLE IF NOT EXISTS atlas.dataset_registry (
    dataset_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    format TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT,
    checksum TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    invalid_rows INTEGER NOT NULL DEFAULT 0,
    manifest JSONB NOT NULL,
    lineage JSONB NOT NULL,
    storage_path TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dataset_registry_category
    ON atlas.dataset_registry (category, registered_at DESC);

CREATE TABLE IF NOT EXISTS atlas.dataset_records (
    dataset_id UUID NOT NULL REFERENCES atlas.dataset_registry(dataset_id),
    row_number INTEGER NOT NULL,
    category TEXT NOT NULL,
    record JSONB NOT NULL,
    valid BOOLEAN NOT NULL,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (dataset_id, row_number)
);

CREATE INDEX IF NOT EXISTS idx_dataset_records_dataset_valid
    ON atlas.dataset_records (dataset_id, valid, row_number);
