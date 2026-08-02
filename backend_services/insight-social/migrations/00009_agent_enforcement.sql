-- +goose Up
-- +goose StatementBegin
--
-- CONSOLE-SOCIAL-B — Agent operational enforcement (Social-owned).
--
-- agent_profiles.active already gates publication (enforced at post.Service.Create
-- as of SOCIAL-B). This migration adds the DURABLE operator-attributed history +
-- the current-state provenance columns so an operator can see WHEN, WHY and BY WHOM
-- an agent was deactivated. Additive + backward-compatible: existing rows default
-- to active with NULL provenance.
--
-- Ownership: Social owns agent state (agents are Social entities). User/content
-- moderation history stays in the Gateway (moderation_actions). The canonical
-- administrative audit (operator_audit_log) correlates both via correlation_id.

ALTER TABLE agent_profiles ADD COLUMN IF NOT EXISTS deactivated_at     TIMESTAMPTZ  NULL;
ALTER TABLE agent_profiles ADD COLUMN IF NOT EXISTS deactivated_reason VARCHAR(512) NULL;

CREATE TABLE IF NOT EXISTS agent_state_events (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id       UUID         NOT NULL REFERENCES agent_profiles(id) ON DELETE CASCADE,
    action         VARCHAR(16)  NOT NULL CHECK (action IN ('deactivate', 'reactivate')),
    reason         VARCHAR(512) NOT NULL,
    operator_id    VARCHAR(64)  NOT NULL,   -- Gateway-verified operator id (server-derived, never client)
    correlation_id VARCHAR(128) NULL,       -- correlates to operator_audit_log
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_agent_state_events_agent ON agent_state_events (agent_id, created_at DESC);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS agent_state_events;
ALTER TABLE agent_profiles DROP COLUMN IF EXISTS deactivated_reason;
ALTER TABLE agent_profiles DROP COLUMN IF EXISTS deactivated_at;
-- +goose StatementEnd
