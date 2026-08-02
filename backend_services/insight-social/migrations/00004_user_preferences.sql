-- +goose Up
-- +goose StatementBegin
--
-- Sprint D — User preferences (settings page).
--
-- 1:1 with users. Created on first read (UPSERT-style) so we don't
-- need a backfill for existing rows; missing preferences resolve to
-- the column defaults at SELECT time.
--
-- digest_frequency CHECK keeps invalid values out — the only writer
-- is the gateway BFF (which already validates), so this is a
-- defence-in-depth backstop.

CREATE TABLE user_preferences (
    user_id          UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    locale           VARCHAR(8)  NOT NULL DEFAULT 'pt-BR',
    push_enabled     BOOLEAN     NOT NULL DEFAULT FALSE,
    email_enabled    BOOLEAN     NOT NULL DEFAULT FALSE,
    digest_frequency VARCHAR(16) NOT NULL DEFAULT 'daily',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (digest_frequency IN ('daily', 'weekly', 'never'))
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS user_preferences;
-- +goose StatementEnd
