-- Nexus Sprint 2 — foundation schema.
--
-- Tables: agents (the persisted, editable communication personas),
-- agent_memories (continuity), agent_drafts (structured communication
-- drafts), agent_publications (queue candidates).
--
-- The five official agents are SEEDS, not code: the router reads the
-- table; admin APIs edit it. Re-running is a no-op (idempotent DDL +
-- ON CONFLICT DO NOTHING seeds).

BEGIN;

CREATE SCHEMA IF NOT EXISTS nexus;

CREATE TABLE IF NOT EXISTS nexus.agents (
    id              UUID         PRIMARY KEY,
    name            VARCHAR(64)  NOT NULL UNIQUE,
    avatar          VARCHAR(512) NOT NULL DEFAULT '',
    bio             TEXT         NOT NULL DEFAULT '',
    active          BOOLEAN      NOT NULL DEFAULT true,
    specialty       VARCHAR(128) NOT NULL,
    trend_types     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    posting_rules   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    rag_sources     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    system_context  TEXT         NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS nexus.agent_memories (
    id          UUID         PRIMARY KEY,
    agent_id    UUID         NOT NULL REFERENCES nexus.agents(id),
    match_id    VARCHAR(64)  NOT NULL,
    trend_id    VARCHAR(64)  NOT NULL,
    summary     TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_memories_agent_match
    ON nexus.agent_memories (agent_id, match_id, created_at DESC);

CREATE TABLE IF NOT EXISTS nexus.agent_drafts (
    id          UUID         PRIMARY KEY,
    agent_id    UUID         NOT NULL REFERENCES nexus.agents(id),
    trend_id    VARCHAR(64)  NOT NULL,
    match_id    VARCHAR(64)  NOT NULL,
    title       VARCHAR(256) NOT NULL,
    summary     TEXT         NOT NULL DEFAULT '',
    highlights  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    charts      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    metadata    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    status      VARCHAR(16)  NOT NULL DEFAULT 'generated',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_drafts_agent
    ON nexus.agent_drafts (agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_agent_drafts_trend
    ON nexus.agent_drafts (trend_id);

CREATE TABLE IF NOT EXISTS nexus.agent_publications (
    id          UUID         PRIMARY KEY,
    draft_id    UUID         NOT NULL REFERENCES nexus.agent_drafts(id),
    agent_id    UUID         NOT NULL REFERENCES nexus.agents(id),
    trend_id    VARCHAR(64)  NOT NULL,
    queue       VARCHAR(128) NOT NULL,
    priority    BOOLEAN      NOT NULL DEFAULT false,
    status      VARCHAR(16)  NOT NULL DEFAULT 'queued',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_publications_agent
    ON nexus.agent_publications (agent_id, created_at DESC);

-- ---- the five official agents (seeds — fully editable afterwards) ----

INSERT INTO nexus.agents
    (id, name, avatar, bio, active, specialty, trend_types, system_context)
VALUES
    ('a0000000-0000-4000-8000-000000000001', 'ninja',
     'avatars/ninja.png',
     'Market intelligence specialist. Reads bookmaker behaviour, odds movement and market divergence.',
     true, 'Market Intelligence',
     '["market_shift","market_conviction","market_acceleration","market_disagreement","market_anomaly","ninja"]'::jsonb,
     'You analyse betting market behaviour from Atlas market trends.'),
    ('a0000000-0000-4000-8000-000000000002', 'pulse',
     'avatars/pulse.png',
     'Match momentum specialist. Tracks pressure, dominance and breakthrough conditions.',
     true, 'Match Momentum',
     '["momentum_shift","pressure_building","dominance_pattern","imminent_breakthrough","tempo_change","pulse"]'::jsonb,
     'You analyse in-match momentum from Atlas momentum trends.'),
    ('a0000000-0000-4000-8000-000000000003', 'oracle',
     'avatars/oracle.png',
     'Historical context specialist. Connects current behaviour to past patterns.',
     true, 'Historical Context',
     '["historical_deviation","historical_pattern","historical_similarity","oracle"]'::jsonb,
     'You analyse historical context from Atlas historical trends and pattern memory.'),
    ('a0000000-0000-4000-8000-000000000004', 'sentinel',
     'avatars/sentinel.png',
     'Risk assessment specialist. Watches impact events, risk escalation and game state.',
     true, 'Risk Assessment',
     '["impact_assessment","risk_increase","risk_escalation","game_state_change","sentinel"]'::jsonb,
     'You analyse match risk from Atlas impact trends.'),
    ('a0000000-0000-4000-8000-000000000005', 'echo',
     'avatars/echo.png',
     'Narrative intelligence specialist. Reads community signals and crowd-market divergence.',
     true, 'Narrative Intelligence',
     '["narrative_divergence","narrative_conflict","sentiment_shift","community_signal","echo"]'::jsonb,
     'You analyse narrative dynamics from Atlas narrative trends.')
ON CONFLICT (id) DO NOTHING;

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS nexus.agent_publications;
-- DROP TABLE IF EXISTS nexus.agent_drafts;
-- DROP TABLE IF EXISTS nexus.agent_memories;
-- DROP TABLE IF EXISTS nexus.agents;
-- COMMIT;
