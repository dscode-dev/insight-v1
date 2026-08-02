-- CONSOLE-SECURITY-A1 — evolve operator_audit_log into the canonical administrative
-- audit spine. ADDITIVE + backward-compatible: existing moderation/auth audit rows
-- keep working (new columns NULL). No column renames, no data rewrite.

-- +goose Up
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS capability            TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS correlation_id        TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS session_id            TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS target_environment    TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS target_service        TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS target_resource_type  TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS target_resource_id    TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS authz_decision        TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS authz_reason_code     TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS outcome_status        TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS idempotency_key       TEXT;
ALTER TABLE operator_audit_log ADD COLUMN IF NOT EXISTS source                TEXT;

-- Idempotent persistence: one canonical row per audit submission. Partial unique so
-- existing rows (NULL idempotency_key) are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS ux_operator_audit_idempotency
  ON operator_audit_log (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_operator_audit_correlation
  ON operator_audit_log (correlation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_operator_audit_capability
  ON operator_audit_log (capability, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_operator_audit_outcome
  ON operator_audit_log (outcome_status, created_at DESC);
-- Keyset pagination for the canonical read.
CREATE INDEX IF NOT EXISTS ix_operator_audit_created_id
  ON operator_audit_log (created_at DESC, id DESC);

-- +goose Down
DROP INDEX IF EXISTS ix_operator_audit_created_id;
DROP INDEX IF EXISTS ix_operator_audit_outcome;
DROP INDEX IF EXISTS ix_operator_audit_capability;
DROP INDEX IF EXISTS ix_operator_audit_correlation;
DROP INDEX IF EXISTS ux_operator_audit_idempotency;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS source;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS idempotency_key;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS outcome_status;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS authz_reason_code;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS authz_decision;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS target_resource_id;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS target_resource_type;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS target_service;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS target_environment;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS session_id;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS correlation_id;
ALTER TABLE operator_audit_log DROP COLUMN IF EXISTS capability;
