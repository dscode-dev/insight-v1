-- +goose Up
-- +goose StatementBegin
--
-- SHARES-V1 — compartilhamento, the social action.
--
-- WHY THIS IS NOT `boosts`. That table already exists and looks adjacent, but
-- it carries `weight`, `boost_type` and `expires_at`: it is an amplification
-- and ranking mechanism — how hard a post is pushed, for how long. A share is
-- a user telling someone about a post. Reusing `boosts` would have made a
-- product action indistinguishable from a ranking lever, and every count of
-- one would silently include the other.
--
-- TWO KINDS, ONE TABLE. `feed` is a repost onto the sharer's own timeline —
-- an in-network action with a subject who can see it. `external` is the post
-- leaving Insight (a copied link, a send to another app); nothing comes back,
-- and all the platform can record is that it happened. They differ in what
-- they mean, not in shape, so they share a table and are told apart by
-- `target` — a caller counting "shares" gets both, which is what a share
-- count means to a user.
--
CREATE TABLE IF NOT EXISTS post_shares (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id    UUID        NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id    UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target     VARCHAR(16) NOT NULL,
    -- Where an external share went, when the client knows ("whatsapp",
    -- "copy_link"). Never required: the client often cannot tell, and a
    -- mandatory field would be filled with a guess.
    channel    VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT post_shares_target_check CHECK (target IN ('feed', 'external')),
    -- A channel only means something for an external share; on a repost it
    -- would be a field nobody can interpret.
    CONSTRAINT post_shares_channel_scope_check
        CHECK (target = 'external' OR channel IS NULL)
);

-- ON DELETE CASCADE, unlike posts→competitions. A share is a fact ABOUT a
-- post; when the post is gone the share describes nothing. Competitions are
-- the opposite — the conversation outlives the competition, which is why that
-- one is RESTRICT.

-- A repost is a state, not an event: you have either reposted a post or you
-- have not, and the button is a toggle. PARTIAL, so it constrains only `feed`.
CREATE UNIQUE INDEX IF NOT EXISTS ux_post_shares_feed_once
    ON post_shares (user_id, post_id)
    WHERE target = 'feed';

-- External shares are events and repeat by nature: the same person sends the
-- same post to two friends. Deduplicating them would undercount the thing the
-- metric exists to measure.

-- The count beside a post, and the "who shared this" list.
CREATE INDEX IF NOT EXISTS ix_post_shares_post ON post_shares (post_id, created_at DESC);
-- A user's own reposts, for their timeline.
CREATE INDEX IF NOT EXISTS ix_post_shares_user ON post_shares (user_id, created_at DESC);

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS post_shares;
-- +goose StatementEnd
