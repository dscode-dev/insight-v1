-- Administrative identity, owned by the Insight Control Plane.
--
-- insight-context.md v2.0 assigns "Autenticação administrativa, Sessões de
-- operadores, RBAC, Operational Identity, Delegation, Audit Spine,
-- Capabilities, Registries" to the Control Plane, and states plainly
-- that the Insight Gateway is NOT responsible for "Administração,
-- Operadores, Console, Auditoria administrativa".
--
-- Until now the console authenticated operators against the Gateway
-- (`POST /v1/operator/auth/login` on the public API), which put
-- administrative identity in the Product Plane — the one place the
-- architecture forbids it, and it also made the whole Intelligence
-- plane unable to authenticate anyone without reaching the internet.
--
-- Own schema rather than `public`: this database already hosts `atlas`
-- and `nexus`, and each domain stays authority over its own data.

CREATE SCHEMA IF NOT EXISTS control_plane;

CREATE TABLE IF NOT EXISTS control_plane.operators (
    id            UUID PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL,
    -- Opaque, self-describing digest produced by the Control Plane
    -- (scrypt). Deliberately NOT pgcrypto's crypt(): verifying in the
    -- database means sending the plaintext password in a query, where
    -- it lands in pg_stat_activity and any statement logging.
    password_hash TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,

    CONSTRAINT ck_operators_role CHECK (role IN (
        'SuperAdmin', 'PlatformAdmin', 'Operations',
        'Support', 'MLAdmin', 'Moderator', 'ReadOnly'
    ))
);

CREATE TABLE IF NOT EXISTS control_plane.operator_sessions (
    id           UUID PRIMARY KEY,
    operator_id  UUID NOT NULL REFERENCES control_plane.operators(id) ON DELETE CASCADE,
    -- sha256 of the opaque token. The token itself is never stored:
    -- a database leak must not hand over live sessions.
    token_hash   TEXT UNIQUE NOT NULL,
    issued_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    revoked_at   TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_agent   TEXT,
    ip_address   TEXT
);

-- Session lookup happens on EVERY authenticated request.
CREATE INDEX IF NOT EXISTS ix_operator_sessions_token_hash
    ON control_plane.operator_sessions (token_hash);

-- "Revoke every session for this operator" on deactivation/logout-all.
CREATE INDEX IF NOT EXISTS ix_operator_sessions_operator_active
    ON control_plane.operator_sessions (operator_id)
    WHERE revoked_at IS NULL;

-- Sweeping expired rows.
CREATE INDEX IF NOT EXISTS ix_operator_sessions_expires_at
    ON control_plane.operator_sessions (expires_at);

-- Audit Spine. The console already emits administrative intent/outcome
-- events; this is where they become durable on the Control Plane side
-- instead of depending on a Gateway the Intelligence plane must not
-- reach for administration.
CREATE TABLE IF NOT EXISTS control_plane.operator_audit_log (
    id             UUID PRIMARY KEY,
    operator_id    UUID REFERENCES control_plane.operators(id) ON DELETE SET NULL,
    event_type     TEXT NOT NULL,
    capability     TEXT,
    outcome        TEXT,
    correlation_id TEXT,
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_operator_audit_created_at
    ON control_plane.operator_audit_log (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_operator_audit_operator
    ON control_plane.operator_audit_log (operator_id, created_at DESC);

-- Rollback:
--
-- BEGIN;
-- DROP SCHEMA IF EXISTS control_plane CASCADE;
-- COMMIT;
