-- +goose Up
-- +goose StatementBegin
--
-- Sprint B — Reactions on Discussion threads.
--
-- Scope (Sprint B): Discussion reactions only. Signal/Message
-- reactions are deferred because the Flutter UI only exposes the
-- heart button on Discussion-kind feed cards today; expanding the
-- target surface would require a polymorphic target_id column
-- (since signals.id is BIGINT, not UUID), and a small step-2
-- migration is preferable to a polymorphic schema we don't need yet.
--
-- Uniqueness: (user_id, discussion_id, kind) — one like per user per
-- discussion. Re-react = idempotent (the unique violation is caught
-- and translated by the repo).
--
-- Reaction count on discussions: NOT denormalised here. The repo
-- computes it on-demand via a COUNT subquery joined into the
-- Discussion read paths. Promote to a counter column if read load
-- ever makes the per-read count expensive.

CREATE TABLE reactions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    discussion_id   UUID NOT NULL REFERENCES discussions(id) ON DELETE CASCADE,
    kind            VARCHAR(16) NOT NULL DEFAULT 'like',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, discussion_id, kind)
);

-- Covering index for "list reactions for discussion" + "did user X react"
-- queries. The unique constraint already creates an index on
-- (user_id, discussion_id, kind) — this one supports the reverse
-- lookup path.
CREATE INDEX ix_reactions_discussion_kind ON reactions (discussion_id, kind);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS reactions;
-- +goose StatementEnd
