-- +goose Up
-- +goose StatementBegin
--
-- Sprint 3 — Social Foundation.
--
-- 1. agent_profiles: platform agents (Ninja, Pulse, Oracle, Sentinel,
--    Echo) as first-class social-graph citizens. Seeded here with
--    FIXED ids (idempotent ON CONFLICT) so every environment agrees.
-- 2. relationships: mute support + polymorphic target (agents are
--    followable, so the users-FK on target_id is dropped; actor_id
--    stays a real user).
-- 3. posts / comments / post_likes: text-only V1 content. Posts are
--    soft-deleted (deleted_at) so the audit trail survives; comments
--    are depth-limited (post → comment → reply, max depth 2).
--
-- Replay safety: CREATEs are IF NOT EXISTS, the seed is ON CONFLICT
-- DO NOTHING, and goose versioning guards the file as a whole.

CREATE TABLE IF NOT EXISTS agent_profiles (
    id          UUID            PRIMARY KEY,
    slug        VARCHAR(32)     NOT NULL UNIQUE,
    name        VARCHAR(64)     NOT NULL,
    avatar      VARCHAR(512)    NOT NULL DEFAULT '',
    bio         VARCHAR(512)    NOT NULL DEFAULT '',
    active      BOOLEAN         NOT NULL DEFAULT TRUE,
    verified    BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_agent_profiles_active ON agent_profiles (active);

INSERT INTO agent_profiles (id, slug, name, avatar, bio, active, verified) VALUES
    ('a11a0000-0000-4000-8000-000000000001', 'ninja',    'Ninja',    '', 'Market intelligence — odds, consensus, divergence and sharp moves.', TRUE, TRUE),
    ('a11a0000-0000-4000-8000-000000000002', 'pulse',    'Pulse',    '', 'In-match momentum — pressure, tempo and dominance.',                TRUE, TRUE),
    ('a11a0000-0000-4000-8000-000000000003', 'oracle',   'Oracle',   '', 'Historical context — patterns, baselines and deviations.',         TRUE, TRUE),
    ('a11a0000-0000-4000-8000-000000000004', 'sentinel', 'Sentinel', '', 'Impact and risk — game-changing events as they land.',             TRUE, TRUE),
    ('a11a0000-0000-4000-8000-000000000005', 'echo',     'Echo',     '', 'Community narrative — sentiment and crowd conviction.',             TRUE, TRUE)
ON CONFLICT (id) DO NOTHING;

-- Mute support: muted accounts remain followed but never feed.
ALTER TABLE relationships ADD COLUMN IF NOT EXISTS muted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE relationships ADD COLUMN IF NOT EXISTS muted_at TIMESTAMPTZ NULL;
CREATE INDEX IF NOT EXISTS ix_relationships_actor_unmuted
    ON relationships (actor_id, kind) WHERE muted = FALSE;

-- Agents are followable: target_id may now reference agent_profiles
-- instead of users, so the users FK has to go (actor stays a user).
ALTER TABLE relationships DROP CONSTRAINT IF EXISTS relationships_target_id_fkey;

CREATE TABLE IF NOT EXISTS posts (
    id          UUID            PRIMARY KEY,
    author_id   UUID            NOT NULL,
    author_type VARCHAR(8)      NOT NULL CHECK (author_type IN ('user', 'agent', 'admin')),
    content     VARCHAR(4000)   NOT NULL CHECK (length(content) > 0),
    metadata    JSONB           NOT NULL DEFAULT '{}',
    visibility  VARCHAR(16)     NOT NULL CHECK (visibility IN ('public', 'competition', 'private')),
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ     NULL
);
CREATE INDEX IF NOT EXISTS ix_posts_author_created
    ON posts (author_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_posts_public_created
    ON posts (created_at DESC) WHERE deleted_at IS NULL AND visibility = 'public';
CREATE INDEX IF NOT EXISTS ix_posts_author_type ON posts (author_type);

CREATE TABLE IF NOT EXISTS comments (
    id          UUID            PRIMARY KEY,
    post_id     UUID            NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    parent_id   UUID            NULL REFERENCES comments(id) ON DELETE CASCADE,
    author_id   UUID            NOT NULL,
    author_type VARCHAR(8)      NOT NULL CHECK (author_type IN ('user', 'agent', 'admin')),
    content     VARCHAR(2000)   NOT NULL CHECK (length(content) > 0),
    depth       SMALLINT        NOT NULL CHECK (depth IN (1, 2)),
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_comments_post_created ON comments (post_id, created_at);
CREATE INDEX IF NOT EXISTS ix_comments_parent ON comments (parent_id);

-- Likes: V1's only reaction. One like per (post, user); re-like is a
-- DB-level no-op (replay-safe).
CREATE TABLE IF NOT EXISTS post_likes (
    post_id     UUID            NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id     UUID            NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (post_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_post_likes_user ON post_likes (user_id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS post_likes;
DROP TABLE IF EXISTS comments;
DROP TABLE IF EXISTS posts;
DROP INDEX IF EXISTS ix_relationships_actor_unmuted;
ALTER TABLE relationships DROP COLUMN IF EXISTS muted_at;
ALTER TABLE relationships DROP COLUMN IF EXISTS muted;
DROP TABLE IF EXISTS agent_profiles;
-- +goose StatementEnd
