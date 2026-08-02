-- ClickHouse analytics bootstrap (ML-C Step 0).
-- Used by Explorer analytics, Atlas analytics, and future ML datasets.
CREATE DATABASE IF NOT EXISTS explorer_analytics;

-- Dataset quality snapshots (one row per competition/season/source measurement).
CREATE TABLE IF NOT EXISTS explorer_analytics.dataset_quality (
    ts            DateTime DEFAULT now(),
    competition   String,
    season        String,
    source        String,
    records       UInt32,
    validated     UInt32,
    review        UInt32,
    rejected      UInt32,
    quality_score Float32
) ENGINE = MergeTree()
ORDER BY (competition, season, source, ts);

-- Cross-source reconciliation outcomes.
CREATE TABLE IF NOT EXISTS explorer_analytics.source_agreement (
    ts             DateTime DEFAULT now(),
    competition    String,
    season         String,
    total_matches  UInt32,
    multi_source   UInt32,
    agreements     UInt32,
    disagreements  UInt32,
    mean_confidence Float32
) ENGINE = MergeTree()
ORDER BY (competition, season, ts);
