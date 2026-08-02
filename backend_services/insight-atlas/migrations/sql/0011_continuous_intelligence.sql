-- Sprint 3.6 — continuous trend intelligence.
--
-- 1. atlas.trend_timeline — append-only narrative timeline per story
--    (cluster_id = trend lifecycle instance id). Never updated.
-- 2. atlas.story_coherence — latest coherence score per match
--    (agreement between market/match/risk/narrative dimensions).
--
-- ORM mappings: TrendTimelineRow, StoryCoherenceRow.
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

CREATE TABLE IF NOT EXISTS atlas.trend_timeline (
    id               UUID             PRIMARY KEY,
    cluster_id       UUID             NOT NULL,
    ts               TIMESTAMPTZ      NOT NULL,
    trend_id         UUID             NOT NULL,
    trend_type       VARCHAR(48)      NOT NULL,
    lifecycle_state  VARCHAR(16)      NOT NULL DEFAULT '',
    confidence       DOUBLE PRECISION NOT NULL,
    strength         DOUBLE PRECISION NOT NULL,
    summary          VARCHAR(1024)    NOT NULL DEFAULT '',
    meaning          VARCHAR(64)      NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_trend_timeline_cluster
    ON atlas.trend_timeline (cluster_id, ts);

CREATE TABLE IF NOT EXISTS atlas.story_coherence (
    canonical_match_id  UUID             PRIMARY KEY,
    score               DOUBLE PRECISION NOT NULL,
    components          JSONB            NOT NULL DEFAULT '{}'::jsonb,
    computed_at         TIMESTAMPTZ      NOT NULL DEFAULT now()
);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.story_coherence;
-- DROP TABLE IF EXISTS atlas.trend_timeline;
-- COMMIT;
