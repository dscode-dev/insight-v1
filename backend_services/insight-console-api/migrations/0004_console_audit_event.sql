--
-- The console's administrative audit spine, made durable again.
--
-- WHAT WAS BROKEN. `getAuditRepository()` falls back to the Gateway sink
-- (POST /v1/console/audit/events) when no CONSOLE_AUDIT_DATABASE_URL is
-- set. That sink forwards the operator's session Bearer to the Gateway
-- for it to resolve — and the Gateway stopped being the issuer of those
-- sessions when identity moved to the Control Plane. It cannot resolve a
-- token it never minted, so every write failed.
--
-- The spine is fail-closed by design: an AUTHORIZED intent that cannot be
-- durably recorded aborts the mutation. Correct, and it meant EVERY
-- governed action in the console answered 503 — the Quality Gate's
-- promotion approval (which ATLAS_V1_FROZEN.md makes mandatory), every
-- Social enforcement action, and the audit page itself. Silent, because
-- nothing exercises those paths on a healthy deploy.
--
-- THE FIX IS TO STOP CROSSING A PLANE. `PostgresAuditRepository` already
-- exists for exactly this; it just had no table. The console's own
-- administrative record belongs in the Control Plane's own database, next
-- to the operators and sessions it describes — not on the far side of a
-- service that no longer knows who the operator is.
--
-- Deployment pairs this with CONSOLE_AUDIT_DATABASE_URL on the console
-- container. Without that variable the table sits unused and the sink
-- stays on the broken Gateway path.
--
-- UNPREFIXED NAME ON PURPOSE. The repository queries
-- `control_plane_audit_event` with no schema qualifier, so it resolves
-- through search_path. This is NOT the same table as
-- control_plane.operator_audit_log, which the Control Plane writes for
-- its own auth events; they record different things and neither should
-- be made to carry the other's columns.
--
CREATE TABLE IF NOT EXISTS public.control_plane_audit_event (
    event_id                 TEXT PRIMARY KEY,
    occurred_at              TIMESTAMPTZ NOT NULL,
    correlation_id           TEXT,
    request_id               TEXT,

    actor_operator_id        TEXT NOT NULL,
    actor_identity_id        TEXT,
    actor_public_actor       TEXT,
    actor_session_id         TEXT,
    -- TEXT[]: the reader maps it straight to string[]. A comma-joined
    -- string would put role parsing in two places.
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
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- NO foreign key to control_plane.operators. An audit record must outlive
-- the operator it names: deleting an account cannot be allowed to delete,
-- or blank, the evidence of what that account did.

-- The reader's keyset pagination is ORDER BY occurred_at DESC, event_id
-- DESC with a (occurred_at, event_id) < (…) cursor. This index is that
-- exact order, so paging stays a range scan rather than a sort of the
-- whole table.
CREATE INDEX IF NOT EXISTS ix_cp_audit_event_keyset
    ON public.control_plane_audit_event (occurred_at DESC, event_id DESC);

-- The filters the audit page actually offers.
CREATE INDEX IF NOT EXISTS ix_cp_audit_event_actor
    ON public.control_plane_audit_event (actor_operator_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_cp_audit_event_capability
    ON public.control_plane_audit_event (capability, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_cp_audit_event_correlation
    ON public.control_plane_audit_event (correlation_id);
