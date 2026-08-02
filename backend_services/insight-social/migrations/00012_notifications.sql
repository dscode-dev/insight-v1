-- +goose Up
-- +goose StatementBegin
--
-- FEATURE-NOTIFICATIONS-V1 Stage 1 — Notification domain (Social = authority).
--
-- A notification is an IMMUTABLE historical record of a message delivered to
-- ONE user. After insertion, only read_at ever changes (archived_at/deleted_at
-- are future, not V1). The flexible `payload` (jsonb) means new notification
-- variants need NO future migration — no per-type columns.
--
-- Deduplication: UNIQUE (user_id, dedup_key). dedup_key is DETERMINISTIC and
-- content-addressed (e.g. 'reaction:discussion:842:user:18'), never timestamp-
-- based, so one user action produces at most one notification per recipient
-- (no cascade). Inserts use ON CONFLICT DO NOTHING.

CREATE TABLE IF NOT EXISTS notifications (
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE, -- recipient
    type         VARCHAR(32)   NOT NULL CHECK (type IN (
                     'community_join','discussion_reply','mention','reaction','system')),
    priority     VARCHAR(16)   NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
    title        VARCHAR(200)  NOT NULL,
    body         VARCHAR(500)  NOT NULL DEFAULT '',
    target_type  VARCHAR(32)   NOT NULL DEFAULT '',   -- community|discussion|post|user|'' (system)
    target_id    UUID          NULL,
    deeplink     VARCHAR(300)  NOT NULL DEFAULT '',   -- persisted at creation; Gateway validates
    payload      JSONB         NOT NULL DEFAULT '{}',
    dedup_key    VARCHAR(200)  NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    read_at      TIMESTAMPTZ   NULL,                  -- the ONLY mutable field
    UNIQUE (user_id, dedup_key)
);

-- Keyset pagination: per-user, newest first (created_at, id) DESC. Serves both
-- List (all) and the unread_only filter's ordering.
CREATE INDEX IF NOT EXISTS ix_notifications_user_created
    ON notifications (user_id, created_at DESC, id DESC);

-- Unread count + unread-only listing: PARTIAL index on the unread subset keeps
-- the count cheap and the working set small. NOTE (evolution point): V1 uses a
-- COUNT over this partial index; at very high volume this should move to a
-- materialized counter or cache — documented in PERFORMANCE.md.
CREATE INDEX IF NOT EXISTS ix_notifications_unread
    ON notifications (user_id, created_at DESC, id DESC) WHERE read_at IS NULL;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP INDEX IF EXISTS ix_notifications_unread;
DROP INDEX IF EXISTS ix_notifications_user_created;
DROP TABLE IF EXISTS notifications;
-- +goose StatementEnd
