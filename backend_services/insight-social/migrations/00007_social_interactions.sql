-- +goose Up
-- +goose StatementBegin
--
-- AZTECA-SOCIAL-A — Saved Posts + Boosts as first-class domain entities.
--
-- insight-social is the single source of truth for both. The Gateway exposes
-- thin BFF endpoints (/v1/posts/{id}/save, /v1/posts/{id}/boost,
-- /v1/me/saved-posts); the mobile client never persists locally and never
-- computes ranking — Boost only records intent + weight; feed priority is the
-- backend's job.

-- ---- Saved Posts -----------------------------------------------------------
-- A user privately bookmarks a post. Separate from likes. The (user_id,
-- post_id) uniqueness makes save idempotent; re-saving is a no-op.
CREATE TABLE IF NOT EXISTS saved_posts (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id     UUID            NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id     UUID            NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, post_id)
);

-- "My saved posts, newest first" (GET /v1/me/saved-posts).
CREATE INDEX IF NOT EXISTS ix_saved_posts_user
    ON saved_posts (user_id, created_at DESC);

-- ---- Boosts ----------------------------------------------------------------
-- A boost is a first-class entity, not a counter. V1 only emits boost_type
-- 'manual'; the remaining types are PREPARED so future producers (Atlas /
-- editorial / paid / reputation) can write boosts without a schema change.
-- `weight` + `status` + `expires_at` let the ranking pipeline (backend-owned)
-- decay and expire boosts. The client only toggles its own manual boost.
CREATE TABLE IF NOT EXISTS boosts (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id     UUID            NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id     UUID            NOT NULL,
    boost_type  VARCHAR(16)     NOT NULL DEFAULT 'manual'
                    CHECK (boost_type IN ('manual', 'atlas', 'editorial', 'paid', 'reputation')),
    weight      INTEGER         NOT NULL DEFAULT 1 CHECK (weight >= 0),
    status      VARCHAR(16)     NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'expired', 'revoked')),
    expires_at  TIMESTAMPTZ     NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- One boost row per (user, post, type) — manual boost toggles idempotently
    -- by flipping status rather than inserting duplicates.
    UNIQUE (user_id, post_id, boost_type)
);

-- Active boosts for a post (ranking reads + the post's boost count).
CREATE INDEX IF NOT EXISTS ix_boosts_post_active
    ON boosts (post_id) WHERE status = 'active';
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS boosts;
DROP TABLE IF EXISTS saved_posts;
-- +goose StatementEnd
