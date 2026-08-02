-- CONSOLE-IDENTITY-A — Operational Identity + Delegation (Gateway is the authority).
-- ADDITIVE + backward-compatible. No renames, no data rewrite. Old audit rows keep
-- working (new columns NULL → read defaults identity_id = operator_id).

-- +goose Up

-- 1) Canonical spine gains identity + delegation + public-actor provenance (all NULLable).
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS identity_id              TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS delegation_id            TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS delegation_subject       TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS delegation_subject_type  TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS public_actor             TEXT;

CREATE INDEX IF NOT EXISTS ix_operator_audit_identity
  ON operator_audit_log (identity_id, created_at DESC) WHERE identity_id IS NOT NULL;

-- 2) Registry of delegatable operational identities (official identities / agents).
--    The operator's OWN identity is NOT stored here — the default path is
--    identity == operator and needs no row. This registry only names the
--    non-operator subjects a grant may reference (display for provenance).
CREATE TABLE IF NOT EXISTS operational_identities (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_type  TEXT NOT NULL CHECK (subject_type IN ('official_identity','agent')),
    subject_id    TEXT NOT NULL,
    display_name  TEXT NOT NULL DEFAULT '',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subject_type, subject_id)
);

-- 3) Delegation grants — the authoritative store. A grant lets ONE operator author
--    actions AS a subject, EXPLICITLY, REVOCABLY, and additively (the operator is
--    always preserved; the subject never replaces it). Not transitive: subject is a
--    terminal identity, never another operator.
CREATE TABLE IF NOT EXISTS delegation_grants (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id   UUID NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
    subject_type  TEXT NOT NULL CHECK (subject_type IN ('official_identity','agent')),
    subject_id    TEXT NOT NULL,
    mode          TEXT NOT NULL CHECK (mode IN ('act_as_identity','act_through_agent')),
    scope         TEXT[] NOT NULL DEFAULT '{}',
    reason        TEXT NOT NULL,
    public_actor  TEXT,                          -- what the public sees; NULL until an official surface renders it
    issued_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_delegation_grants_operator
  ON delegation_grants (operator_id, issued_at DESC);
-- Fast "is this grant currently usable by this operator" lookup (resolution).
CREATE INDEX IF NOT EXISTS ix_delegation_grants_live
  ON delegation_grants (operator_id) WHERE revoked_at IS NULL;

-- +goose Down
DROP INDEX IF EXISTS ix_delegation_grants_live;
DROP INDEX IF EXISTS ix_delegation_grants_operator;
DROP TABLE IF EXISTS delegation_grants;
DROP TABLE IF EXISTS operational_identities;
DROP INDEX IF EXISTS ix_operator_audit_identity;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS public_actor;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS delegation_subject_type;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS delegation_subject;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS delegation_id;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS identity_id;
