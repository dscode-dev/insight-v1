-- CONSOLE-SECURITY-A0 — canonical administrative audit store (durable).
-- Superset-compatible with the Gateway operator_audit_log so the two federate by
-- correlation_id (ADR-0005: one canonical spine). Apply with the repository's
-- production migration tooling; activated by CONSOLE_AUDIT_DATABASE_URL.
--
-- Ownership note: this is the interim Console-owned Control Plane audit store.
-- The target is a Gateway audit-ingest endpoint that writes to operator_audit_log
-- directly; see CONSOLE_SECURITY_A0_AUDIT_SPINE.md.

CREATE TABLE IF NOT EXISTS control_plane_audit_event (
  event_id                 UUID PRIMARY KEY,
  occurred_at              TIMESTAMPTZ NOT NULL,
  correlation_id           TEXT,
  request_id               TEXT,

  actor_operator_id        TEXT NOT NULL,
  actor_identity_id        TEXT,
  actor_session_id         TEXT NOT NULL,
  actor_roles              TEXT[] NOT NULL DEFAULT '{}',

  delegation_active        BOOLEAN NOT NULL DEFAULT FALSE,
  delegation_subject_type  TEXT,
  delegation_subject_id    TEXT,
  delegation_mode          TEXT,
  delegation_grant_id      TEXT,

  capability               TEXT NOT NULL,
  action_domain            TEXT,
  action_resource          TEXT,
  action_action            TEXT,

  target_environment_id    TEXT,
  target_service_id        TEXT,
  target_resource_type     TEXT,
  target_resource_id       TEXT,

  authz_decision           TEXT NOT NULL,
  authz_reason_code        TEXT,
  authz_policy_source      TEXT,

  outcome_status           TEXT NOT NULL,
  outcome_error_code       TEXT,
  outcome_retryable        BOOLEAN NOT NULL DEFAULT FALSE,

  reason                   TEXT,
  metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deterministic keyset pagination + common filters.
CREATE INDEX IF NOT EXISTS ix_cpae_occurred_at_event ON control_plane_audit_event (occurred_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS ix_cpae_correlation      ON control_plane_audit_event (correlation_id);
CREATE INDEX IF NOT EXISTS ix_cpae_operator         ON control_plane_audit_event (actor_operator_id);
CREATE INDEX IF NOT EXISTS ix_cpae_capability       ON control_plane_audit_event (capability);
CREATE INDEX IF NOT EXISTS ix_cpae_service          ON control_plane_audit_event (target_service_id);
CREATE INDEX IF NOT EXISTS ix_cpae_environment      ON control_plane_audit_event (target_environment_id);
CREATE INDEX IF NOT EXISTS ix_cpae_outcome          ON control_plane_audit_event (outcome_status);
