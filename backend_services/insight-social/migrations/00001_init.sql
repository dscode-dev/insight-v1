-- +goose Up
-- +goose StatementBegin
--
-- Ported byte-for-byte from plaza-py alembic revision
-- 20260522_0001_init.py.
--
-- The plaza-py revision stays the source of truth UNTIL the cutover
-- script seeds goose_db_version with this migration marked applied
-- (tools/seed_goose_marker.sh). After that, plaza-py is FROZEN — no
-- new alembic revisions allowed (enforced by docs + CI guard).
--
-- Schema lives in `insight_social` (Phase 3 logical DB separation).
-- Tables are declared in FK dependency order: parents first.

-- ---------- users ----------
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(32)  NOT NULL UNIQUE,
    display_name    VARCHAR(64)  NOT NULL,
    initials        VARCHAR(4)   NOT NULL,
    accent_color    VARCHAR(7)   NOT NULL,
    reputation      INTEGER      NOT NULL DEFAULT 50,
    tier            VARCHAR(16)  NOT NULL DEFAULT 'scout',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_users_tier ON users (tier);
CREATE INDEX ix_users_created_at ON users (created_at);

-- ---------- competitions ----------
CREATE TABLE competitions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            VARCHAR(48)  NOT NULL UNIQUE,
    name            VARCHAR(120) NOT NULL,
    short_name      VARCHAR(32)  NOT NULL,
    sport           VARCHAR(24)  NOT NULL DEFAULT 'football',
    region          VARCHAR(48)  NOT NULL,
    accent_color    VARCHAR(7)   NOT NULL DEFAULT '#5BA8FF',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_competitions_is_active ON competitions (is_active);

-- ---------- matches ----------
CREATE TABLE matches (
    match_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competition_id  UUID         NOT NULL REFERENCES competitions(id) ON DELETE RESTRICT,
    home_team_id    VARCHAR(48)  NOT NULL,
    home_team_name  VARCHAR(80)  NOT NULL,
    home_team_short VARCHAR(8)   NOT NULL,
    home_team_color VARCHAR(7)   NOT NULL,
    away_team_id    VARCHAR(48)  NOT NULL,
    away_team_name  VARCHAR(80)  NOT NULL,
    away_team_short VARCHAR(8)   NOT NULL,
    away_team_color VARCHAR(7)   NOT NULL,
    kickoff_ts      TIMESTAMPTZ  NOT NULL,
    state           VARCHAR(16)  NOT NULL DEFAULT 'scheduled',
    home_score      INTEGER,
    away_score      INTEGER,
    minute          INTEGER,
    period          VARCHAR(16)
);
CREATE INDEX ix_matches_competition_id ON matches (competition_id);
CREATE INDEX ix_matches_kickoff_ts ON matches (kickoff_ts);
CREATE INDEX ix_matches_state ON matches (state);

-- ---------- communities ----------
CREATE TABLE communities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            VARCHAR(48)  NOT NULL UNIQUE,
    name            VARCHAR(80)  NOT NULL,
    topic           VARCHAR(160) NOT NULL,
    kind            VARCHAR(24)  NOT NULL DEFAULT 'topic',
    competition_id  UUID         REFERENCES competitions(id) ON DELETE SET NULL,
    accent_color    VARCHAR(7)   NOT NULL,
    member_count    INTEGER      NOT NULL DEFAULT 0,
    active_now      INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_communities_kind ON communities (kind);
CREATE INDEX ix_communities_competition_id ON communities (competition_id);

-- ---------- community_members ----------
CREATE TABLE community_members (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    community_id    UUID         NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    is_moderator    BOOLEAN      NOT NULL DEFAULT FALSE,
    joined_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, community_id)
);
CREATE INDEX ix_community_members_community_id ON community_members (community_id);

-- ---------- discussions ----------
CREATE TABLE discussions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    community_id        UUID         NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    author_id           UUID         REFERENCES users(id) ON DELETE SET NULL,
    title               VARCHAR(200) NOT NULL,
    body                TEXT         NOT NULL,
    match_id            UUID         REFERENCES matches(match_id) ON DELETE SET NULL,
    message_count       INTEGER      NOT NULL DEFAULT 0,
    participant_count   INTEGER      NOT NULL DEFAULT 0,
    last_activity_ts    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_discussions_community_id ON discussions (community_id);
CREATE INDEX ix_discussions_match_id ON discussions (match_id);
CREATE INDEX ix_discussions_last_activity_ts ON discussions (last_activity_ts);

-- ---------- discussion_messages ----------
CREATE TABLE discussion_messages (
    id              BIGSERIAL PRIMARY KEY,
    discussion_id   UUID         NOT NULL REFERENCES discussions(id) ON DELETE CASCADE,
    author_id       UUID         REFERENCES users(id) ON DELETE SET NULL,
    body            TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_discussion_messages_discussion_id ON discussion_messages (discussion_id);
CREATE INDEX ix_discussion_messages_created_at ON discussion_messages (created_at);

-- ---------- signals (HumanSignal events) ----------
CREATE TABLE signals (
    id                      BIGSERIAL PRIMARY KEY,
    author_id               UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_id                UUID            REFERENCES matches(match_id) ON DELETE SET NULL,
    kind                    VARCHAR(32)     NOT NULL,
    source                  VARCHAR(24)     NOT NULL DEFAULT 'user',
    direction               VARCHAR(16)     NOT NULL DEFAULT 'neutral',
    value                   NUMERIC(10, 6)  NOT NULL DEFAULT 0,
    confidence              NUMERIC(10, 6)  NOT NULL DEFAULT 0,
    weight_multiplier       NUMERIC(10, 6)  NOT NULL DEFAULT 1.0,
    body                    TEXT,
    minute                  INTEGER,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_signals_author_id ON signals (author_id);
CREATE INDEX ix_signals_match_id ON signals (match_id);
CREATE INDEX ix_signals_kind ON signals (kind);
CREATE INDEX ix_signals_created_at ON signals (created_at);

-- ---------- reputation_events ----------
CREATE TABLE reputation_events (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind                VARCHAR(48)     NOT NULL,
    delta               INTEGER         NOT NULL,
    reason              VARCHAR(200)    NOT NULL,
    related_entity_id   UUID,
    occurred_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_reputation_events_user_id ON reputation_events (user_id);
CREATE INDEX ix_reputation_events_occurred_at ON reputation_events (occurred_at);

-- ---------- sentiment_snapshots ----------
CREATE TABLE sentiment_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    match_id        UUID            NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    home_pct        NUMERIC(10, 6)  NOT NULL,
    draw_pct        NUMERIC(10, 6)  NOT NULL,
    away_pct        NUMERIC(10, 6)  NOT NULL,
    participants    INTEGER         NOT NULL,
    captured_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_sentiment_snapshots_match_id ON sentiment_snapshots (match_id);
CREATE INDEX ix_sentiment_snapshots_captured_at ON sentiment_snapshots (captured_at);

-- ---------- relationships (follow / mute / block) ----------
-- CHECK constraint preserved from alembic: an actor cannot have a
-- relationship with themselves. The UNIQUE (actor, target, kind)
-- enforces idempotency at the DB layer rather than the app, so the
-- Strangler can flip back to plaza-py mid-rollout without corruption.
CREATE TABLE relationships (
    id              BIGSERIAL PRIMARY KEY,
    actor_id        UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_id       UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind            VARCHAR(16)     NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (actor_id, target_id, kind),
    CHECK (actor_id <> target_id)
);
CREATE INDEX ix_relationships_target_id ON relationships (target_id);
CREATE INDEX ix_relationships_kind ON relationships (kind);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
-- Drops in reverse FK order. Leaves gen_random_uuid extension in place
-- (it predates plaza, owned by the platform).
DROP TABLE IF EXISTS relationships;
DROP TABLE IF EXISTS sentiment_snapshots;
DROP TABLE IF EXISTS reputation_events;
DROP TABLE IF EXISTS signals;
DROP TABLE IF EXISTS discussion_messages;
DROP TABLE IF EXISTS discussions;
DROP TABLE IF EXISTS community_members;
DROP TABLE IF EXISTS communities;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS competitions;
DROP TABLE IF EXISTS users;
-- +goose StatementEnd
