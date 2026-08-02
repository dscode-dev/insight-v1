-- 00001_init — initial auth_credentials schema.
--
-- Ports the original atrium-py alembic revision 20260522_0001_init.
-- Schema identical so a database already migrated by atrium-py
-- (skipped by goose via tools/seed_goose_marker.sh) passes verify.

-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS auth_credentials (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL,
    username            VARCHAR(64) NOT NULL,
    password_hash       VARCHAR(256) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at       TIMESTAMPTZ,
    failed_logins_since INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_auth_credentials_user_id UNIQUE (user_id),
    CONSTRAINT uq_auth_credentials_username UNIQUE (username)
);

CREATE INDEX IF NOT EXISTS ix_auth_credentials_user_id
    ON auth_credentials (user_id);

CREATE INDEX IF NOT EXISTS ix_auth_credentials_username
    ON auth_credentials (username);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP INDEX IF EXISTS ix_auth_credentials_username;
DROP INDEX IF EXISTS ix_auth_credentials_user_id;
DROP TABLE IF EXISTS auth_credentials;
-- +goose StatementEnd
