-- 00006_operator_identity — Gateway-owned Console/operator identity.
--
-- Gateway is the single authority for operator credentials, sessions,
-- roles/permissions and audit. Console must consume this surface only.

-- +goose Up
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS operators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator',
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS operator_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id UUID NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_operator_sessions_operator_id
    ON operator_sessions(operator_id);

CREATE INDEX IF NOT EXISTS ix_operator_sessions_live
    ON operator_sessions(operator_id)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS operator_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id UUID REFERENCES operators(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    request_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_operator_audit_log_operator_id
    ON operator_audit_log(operator_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_operator_audit_log_event_type
    ON operator_audit_log(event_type, created_at DESC);

-- +goose Down
DROP INDEX IF EXISTS ix_operator_audit_log_event_type;
DROP INDEX IF EXISTS ix_operator_audit_log_operator_id;
DROP TABLE IF EXISTS operator_audit_log;
DROP INDEX IF EXISTS ix_operator_sessions_live;
DROP INDEX IF EXISTS ix_operator_sessions_operator_id;
DROP TABLE IF EXISTS operator_sessions;
DROP TABLE IF EXISTS operators;
