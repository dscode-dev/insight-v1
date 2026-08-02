-- +goose Up
-- +goose StatementBegin
--
-- FEATURE-SEARCH-V1 (Stage 1) — Search foundation. Additive only.
--
-- 1. posts full-text search: a STORED generated tsvector + GIN index. Config
--    'simple' (deliberate): language-neutral, no stemming surprises, fully
--    deterministic ranking via ts_rank. Only public, non-deleted posts are ever
--    searched (enforced in the query, not the index).
-- 2. pg_trgm + GIN trigram indexes for the "contains" tier on identity-ish
--    columns. pg_trgm is a TRUSTED extension (PG >= 13): CREATE EXTENSION works
--    for the database owner without superuser. If the target cluster somehow
--    lacks it, see the goose notes in FEATURE_SEARCH_V1_ARCHITECTURE.md.
-- 3. search_history: PRIVATE per-user recent searches. Normalized query text,
--    deduped via UNIQUE upsert, pruned to a bounded size on write. Never
--    readable across users (user_id scoping enforced by every query).
--
-- NO teams table. NO players table. Teams/Players are BLOCKED_BY_DOMAIN:
-- match team-name strings stay match CONTEXT and are never promoted to
-- canonical Team identities by this migration or any search query.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------- posts FTS ----------
ALTER TABLE posts ADD COLUMN IF NOT EXISTS search_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;
CREATE INDEX IF NOT EXISTS ix_posts_search_tsv ON posts USING gin (search_tsv);

-- ---------- trigram indexes ("contains" tier) ----------
CREATE INDEX IF NOT EXISTS ix_users_username_trgm
    ON users USING gin (lower(username) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_users_display_name_trgm
    ON users USING gin (lower(display_name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_agent_profiles_name_trgm
    ON agent_profiles USING gin (lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_communities_name_trgm
    ON communities USING gin (lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_communities_topic_trgm
    ON communities USING gin (lower(topic) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_competitions_name_trgm
    ON competitions USING gin (lower(name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_matches_home_team_trgm
    ON matches USING gin (lower(home_team_name) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_matches_away_team_trgm
    ON matches USING gin (lower(away_team_name) gin_trgm_ops);

-- ---------- search history (private per user) ----------
CREATE TABLE IF NOT EXISTS search_history (
    id          BIGSERIAL    PRIMARY KEY,
    user_id     UUID         NOT NULL,
    query       VARCHAR(120) NOT NULL,   -- normalized: trimmed, lowercased, collapsed whitespace
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, query)              -- dedupe: re-searching refreshes created_at
);
CREATE INDEX IF NOT EXISTS ix_search_history_user_recent
    ON search_history (user_id, created_at DESC);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS search_history;
DROP INDEX IF EXISTS ix_matches_away_team_trgm;
DROP INDEX IF EXISTS ix_matches_home_team_trgm;
DROP INDEX IF EXISTS ix_competitions_name_trgm;
DROP INDEX IF EXISTS ix_communities_topic_trgm;
DROP INDEX IF EXISTS ix_communities_name_trgm;
DROP INDEX IF EXISTS ix_agent_profiles_name_trgm;
DROP INDEX IF EXISTS ix_users_display_name_trgm;
DROP INDEX IF EXISTS ix_users_username_trgm;
DROP INDEX IF EXISTS ix_posts_search_tsv;
ALTER TABLE posts DROP COLUMN IF EXISTS search_tsv;
-- extension left installed (shared, trusted; other consumers may exist)
-- +goose StatementEnd
