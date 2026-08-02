-- 00004_moderation — Store-A: UGC safety, EULA acceptance & moderation.
--
-- Moderation is a Gateway (edge BFF) concern: blocks, reports, admin actions,
-- platform-hidden content and user bans all live here. Social stays the pure
-- social graph. The Gateway post-filters the feed/comment/author responses it
-- proxies from Social against this data, and enforces bans in the auth layer.
--
-- EULA: auth_credentials gains accepted_terms_version / accepted_terms_at —
-- account creation is blocked without an accepted Terms version.

-- +goose Up
-- +goose StatementBegin

-- ---- EULA / Terms acceptance (App Store / Play requirement) ----
ALTER TABLE auth_credentials
    ADD COLUMN IF NOT EXISTS accepted_terms_version VARCHAR(32);
ALTER TABLE auth_credentials
    ADD COLUMN IF NOT EXISTS accepted_terms_at TIMESTAMPTZ;

-- ---- Per-user blocks ----
CREATE TABLE IF NOT EXISTS blocked_users (
    blocker_id  UUID NOT NULL,
    blocked_id  UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (blocker_id, blocked_id)
);
CREATE INDEX IF NOT EXISTS ix_blocked_users_blocker ON blocked_users (blocker_id);

-- ---- Reports (post | comment | user) ----
CREATE TABLE IF NOT EXISTS moderation_reports (
    id           UUID PRIMARY KEY,
    reporter_id  UUID NOT NULL,
    target_type  VARCHAR(16) NOT NULL,   -- post | comment | user
    target_id    VARCHAR(64) NOT NULL,
    reason       VARCHAR(32) NOT NULL,   -- inappropriate | hate | spam | violence | other
    description  TEXT,
    status       VARCHAR(16) NOT NULL DEFAULT 'open', -- open | reviewing | resolved | dismissed
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_moderation_reports_status     ON moderation_reports (status);
CREATE INDEX IF NOT EXISTS ix_moderation_reports_target     ON moderation_reports (target_type, target_id);
CREATE INDEX IF NOT EXISTS ix_moderation_reports_reason     ON moderation_reports (reason);
CREATE INDEX IF NOT EXISTS ix_moderation_reports_created_at ON moderation_reports (created_at DESC);

-- ---- Audit log of every admin moderation action ----
CREATE TABLE IF NOT EXISTS moderation_actions (
    id           UUID PRIMARY KEY,
    report_id    UUID,                   -- nullable: some actions are not report-driven
    moderator_id VARCHAR(64) NOT NULL,   -- console operator id/username
    action       VARCHAR(32) NOT NULL,   -- dismiss | remove_content | restore_content | suspend_user | ban_user | restore_user
    target_type  VARCHAR(16) NOT NULL,
    target_id    VARCHAR(64) NOT NULL,
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_moderation_actions_created_at ON moderation_actions (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_moderation_actions_target     ON moderation_actions (target_type, target_id);

-- ---- Platform-hidden content (admin remove_content / restore_content) ----
CREATE TABLE IF NOT EXISTS moderation_hidden_content (
    target_type VARCHAR(16) NOT NULL,    -- post | comment
    target_id   VARCHAR(64) NOT NULL,
    hidden_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (target_type, target_id)
);

-- ---- User moderation state (suspend / ban) ----
CREATE TABLE IF NOT EXISTS moderation_user_state (
    user_id    UUID PRIMARY KEY,
    state      VARCHAR(16) NOT NULL DEFAULT 'active', -- active | suspended | banned
    until      TIMESTAMPTZ,              -- suspension expiry; null = indefinite/ban
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS moderation_user_state;
DROP TABLE IF EXISTS moderation_hidden_content;
DROP TABLE IF EXISTS moderation_actions;
DROP TABLE IF EXISTS moderation_reports;
DROP TABLE IF EXISTS blocked_users;
ALTER TABLE auth_credentials DROP COLUMN IF EXISTS accepted_terms_at;
ALTER TABLE auth_credentials DROP COLUMN IF EXISTS accepted_terms_version;
-- +goose StatementEnd
