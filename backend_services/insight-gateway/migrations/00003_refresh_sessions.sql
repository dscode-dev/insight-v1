-- 00003_refresh_sessions — Auth-A Part 7: server-side refresh sessions.
--
-- Until now refresh was STATELESS (decode JWT → re-issue). That makes refresh
-- tokens impossible to revoke and gives no reuse detection. This table makes
-- each issued refresh token a revocable, rotatable server-side record.
--
-- We store ONLY the SHA-256 hex of the refresh token (token_hash), never the
-- raw JWT — a DB leak then can't be replayed against /v1/auth/refresh.
--
-- Lifecycle:
--   * issueTokens  → INSERT a live row (revoked_at NULL).
--   * Refresh      → lookup by hash; reject if revoked/expired; else revoke the
--                    presented row (rotation) and INSERT a fresh one.
--   * Logout       → revoke by hash (idempotent).

-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS auth_refresh_sessions (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL,
    token_hash  VARCHAR(64) NOT NULL,
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_refresh_sessions_token_hash
    ON auth_refresh_sessions (token_hash);

CREATE INDEX IF NOT EXISTS ix_auth_refresh_sessions_user_id
    ON auth_refresh_sessions (user_id);

-- Partial index for the "live sessions for a user" sweep (logout-all / pruning).
CREATE INDEX IF NOT EXISTS ix_auth_refresh_sessions_live
    ON auth_refresh_sessions (user_id)
    WHERE revoked_at IS NULL;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP INDEX IF EXISTS ix_auth_refresh_sessions_live;
DROP INDEX IF EXISTS ix_auth_refresh_sessions_user_id;
DROP INDEX IF EXISTS uq_auth_refresh_sessions_token_hash;
DROP TABLE IF EXISTS auth_refresh_sessions;
-- +goose StatementEnd
