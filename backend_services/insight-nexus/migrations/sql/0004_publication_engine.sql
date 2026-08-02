-- 0004 — Publication Engine (Sprint 4).
--
-- personas: the five official agent voices (admin-editable; seeded
--   with FIXED Social author ids matching insight-social migration
--   00005).
-- publication_candidates: every publication attempt with FULL
--   explainability (Part 12) — the Console answers "why was this
--   published / suppressed?" from this table alone.
-- publication_tickets: the all-providers-failed human-review queue
--   (Part 14/15) — never auto-published.
-- publication_log: the persisted anti-spam budgets (Part 11).
-- agent_memories: Sprint 4 Part 8 expansion (kind / cluster_id /
--   narrative) — publications become first-class memories.
--
-- Idempotent (IF NOT EXISTS / ON CONFLICT); rollback:
--   DROP TABLE IF EXISTS nexus.publication_log, nexus.publication_tickets,
--     nexus.publication_candidates, nexus.personas;
--   ALTER TABLE nexus.agent_memories DROP COLUMN IF EXISTS kind,
--     DROP COLUMN IF EXISTS cluster_id, DROP COLUMN IF EXISTS narrative;

ALTER TABLE nexus.agent_memories ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'observation';
ALTER TABLE nexus.agent_memories ADD COLUMN IF NOT EXISTS cluster_id UUID NULL;
ALTER TABLE nexus.agent_memories ADD COLUMN IF NOT EXISTS narrative VARCHAR(512) NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_agent_memories_publications
    ON nexus.agent_memories (agent_id, cluster_id, created_at)
    WHERE kind = 'publication';

CREATE TABLE IF NOT EXISTS nexus.personas (
    slug             VARCHAR(32) PRIMARY KEY,
    social_author_id UUID        NOT NULL,
    style            VARCHAR(256) NOT NULL,
    tone             VARCHAR(256) NOT NULL,
    expertise        VARCHAR(512) NOT NULL,
    restrictions     JSONB        NOT NULL DEFAULT '[]',
    posting_behavior VARCHAR(512) NOT NULL DEFAULT '',
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

INSERT INTO nexus.personas (slug, social_author_id, style, tone, expertise, restrictions, posting_behavior) VALUES
  ('ninja',    'a11a0000-0000-4000-8000-000000000001', 'concise and surgical; numbers first, adjectives last', 'calm, confident, market-fluent', 'market intelligence: odds movement, consensus, divergence, sharp repricings', '["never gives betting advice or staking suggestions","never mentions bookmaker margins or arbitrage","never predicts final scores"]', 'posts only on meaningful market behavior; one strong post per story beat'),
  ('pulse',    'a11a0000-0000-4000-8000-000000000002', 'energetic, present-tense, short sentences', 'urgent but never breathless', 'in-match momentum: pressure, tempo, dominance shifts', '["never speculates beyond what the match data shows","never predicts final scores"]', 'follows the live arc: build-up, peak, resolution; quiet between beats'),
  ('oracle',   'a11a0000-0000-4000-8000-000000000003', 'reflective, comparative, references precedent', 'measured, scholarly, lightly wry', 'historical context: patterns, baselines, deviations, recurrences', '["never presents history as a guarantee of the future","never predicts final scores"]', 'posts when history genuinely illuminates the present; never forces a parallel'),
  ('sentinel', 'a11a0000-0000-4000-8000-000000000004', 'factual, structured, risk-first framing', 'alert, precise, unexcitable', 'impact and risk: game-changing events, instability, discipline', '["never dramatizes injuries","never assigns blame to officials or players"]', 'posts on material impact only; silence is acceptable output'),
  ('echo',     'a11a0000-0000-4000-8000-000000000005', 'conversational, crowd-aware, quotes the mood', 'warm, curious, community-first', 'narrative and sentiment: what the crowd believes and how it shifts', '["never presents sentiment as fact","never amplifies toxicity or pile-ons"]', 'posts when community conviction forms or breaks; mirrors, never leads')
ON CONFLICT (slug) DO NOTHING;

CREATE TABLE IF NOT EXISTS nexus.publication_candidates (
    id                 UUID PRIMARY KEY,
    draft_id           UUID NOT NULL,
    agent_id           UUID NOT NULL,
    agent_name         VARCHAR(32) NOT NULL,
    trend_ids          JSONB NOT NULL DEFAULT '[]',
    cluster_id         UUID NULL,
    decision_id        UUID NULL,
    publication_reason VARCHAR(1024) NOT NULL DEFAULT '',
    prompt_version     VARCHAR(16) NOT NULL DEFAULT '',
    provider           VARCHAR(32) NOT NULL DEFAULT '',
    model              VARCHAR(64) NOT NULL DEFAULT '',
    fallback_used      BOOLEAN NOT NULL DEFAULT FALSE,
    fallback_chain     JSONB NOT NULL DEFAULT '[]',
    draft_version      INTEGER NOT NULL DEFAULT 0,
    title              VARCHAR(256) NOT NULL DEFAULT '',
    summary            VARCHAR(1024) NOT NULL DEFAULT '',
    highlights         JSONB NOT NULL DEFAULT '[]',
    tags               JSONB NOT NULL DEFAULT '[]',
    chart_hints        JSONB NOT NULL DEFAULT '[]',
    match_id           VARCHAR(64) NOT NULL DEFAULT '',
    status             VARCHAR(16) NOT NULL,
    status_reason      VARCHAR(1024) NOT NULL DEFAULT '',
    social_post_id     VARCHAR(64) NOT NULL DEFAULT '',
    created_at         TIMESTAMPTZ NOT NULL,
    published_at       TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_pub_candidates_status ON nexus.publication_candidates (status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_pub_candidates_agent ON nexus.publication_candidates (agent_name, created_at DESC);

CREATE TABLE IF NOT EXISTS nexus.publication_tickets (
    id                 UUID PRIMARY KEY,
    agent_id           UUID NOT NULL,
    agent_name         VARCHAR(32) NOT NULL,
    trend_ids          JSONB NOT NULL DEFAULT '[]',
    cluster_id         UUID NULL,
    context            JSONB NOT NULL DEFAULT '{}',
    publication_reason VARCHAR(1024) NOT NULL DEFAULT '',
    suggested_title    VARCHAR(256) NOT NULL DEFAULT '',
    suggested_summary  VARCHAR(1024) NOT NULL DEFAULT '',
    evidence           JSONB NOT NULL DEFAULT '[]',
    priority           VARCHAR(16) NOT NULL DEFAULT '',
    match_id           VARCHAR(64) NOT NULL DEFAULT '',
    status             VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    reviewed_by        VARCHAR(64) NOT NULL DEFAULT '',
    reviewed_at        TIMESTAMPTZ NULL,
    published_by       VARCHAR(64) NOT NULL DEFAULT '',
    published_at       TIMESTAMPTZ NULL,
    created_at         TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pub_tickets_status ON nexus.publication_tickets (status, created_at DESC);

CREATE TABLE IF NOT EXISTS nexus.publication_log (
    id           BIGSERIAL PRIMARY KEY,
    agent_id     UUID NOT NULL,
    cluster_id   UUID NULL,
    trend_id     VARCHAR(64) NOT NULL DEFAULT '',
    match_id     VARCHAR(64) NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pub_log_agent ON nexus.publication_log (agent_id, published_at DESC);
CREATE INDEX IF NOT EXISTS ix_pub_log_cluster ON nexus.publication_log (cluster_id, published_at DESC);
CREATE INDEX IF NOT EXISTS ix_pub_log_trend ON nexus.publication_log (trend_id, published_at DESC);
