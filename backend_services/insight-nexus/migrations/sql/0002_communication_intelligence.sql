-- Nexus Sprint 3 — communication intelligence layer.
--
-- New tables: trend_clusters (story clusters), publication_decisions
-- (every decision stored — no black boxes), agent_states (narrative
-- state machine), draft_evolution (anti-repetition sequence). Plus
-- cluster_type on agent_memories for related-memory retrieval.
--
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

ALTER TABLE nexus.agent_memories
    ADD COLUMN IF NOT EXISTS cluster_type VARCHAR(32) NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_agent_memories_agent_cluster
    ON nexus.agent_memories (agent_id, cluster_type, created_at DESC);

CREATE TABLE IF NOT EXISTS nexus.trend_clusters (
    id            UUID             PRIMARY KEY,
    match_id      VARCHAR(64)      NOT NULL,
    cluster_type  VARCHAR(32)      NOT NULL,
    trend_ids     JSONB            NOT NULL DEFAULT '[]'::jsonb,
    trend_types   JSONB            NOT NULL DEFAULT '[]'::jsonb,
    confidence    DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ      NOT NULL,
    updated_at    TIMESTAMPTZ      NOT NULL,
    UNIQUE (match_id, cluster_type)
);
CREATE INDEX IF NOT EXISTS ix_trend_clusters_match
    ON nexus.trend_clusters (match_id);

CREATE TABLE IF NOT EXISTS nexus.publication_decisions (
    id          UUID             PRIMARY KEY,
    agent_id    UUID             NOT NULL,
    trend_id    VARCHAR(64)      NOT NULL,
    cluster_id  UUID             NOT NULL,
    match_id    VARCHAR(64)      NOT NULL,
    action      VARCHAR(24)      NOT NULL,
    priority    VARCHAR(12)      NOT NULL,
    reasoning   JSONB            NOT NULL DEFAULT '[]'::jsonb,
    confidence  DOUBLE PRECISION NOT NULL,
    created_at  TIMESTAMPTZ      NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_publication_decisions_created
    ON nexus.publication_decisions (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_publication_decisions_action
    ON nexus.publication_decisions (action);

CREATE TABLE IF NOT EXISTS nexus.agent_states (
    id             UUID         PRIMARY KEY,
    agent_id       UUID         NOT NULL,
    match_id       VARCHAR(64)  NOT NULL,
    cluster_id     UUID         NOT NULL,
    cluster_type   VARCHAR(32)  NOT NULL,
    current_state  VARCHAR(16)  NOT NULL,
    history        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at     TIMESTAMPTZ  NOT NULL,
    updated_at     TIMESTAMPTZ  NOT NULL,
    UNIQUE (agent_id, match_id, cluster_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_states_agent
    ON nexus.agent_states (agent_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS nexus.draft_evolution (
    id          UUID         PRIMARY KEY,
    agent_id    UUID         NOT NULL,
    cluster_id  UUID         NOT NULL,
    draft_id    UUID         NOT NULL,
    match_id    VARCHAR(64)  NOT NULL,
    draft_type  VARCHAR(24)  NOT NULL,
    sequence    INTEGER      NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_draft_evolution_cluster
    ON nexus.draft_evolution (agent_id, cluster_id);
CREATE INDEX IF NOT EXISTS ix_draft_evolution_created
    ON nexus.draft_evolution (created_at DESC);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS nexus.draft_evolution;
-- DROP TABLE IF EXISTS nexus.agent_states;
-- DROP TABLE IF EXISTS nexus.publication_decisions;
-- DROP TABLE IF EXISTS nexus.trend_clusters;
-- ALTER TABLE nexus.agent_memories DROP COLUMN IF EXISTS cluster_type;
-- COMMIT;
