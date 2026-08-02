-- 0005 — Console Agent & Publication Control (Sprint 4.5).
--
-- console_audit: the IMMUTABLE operational audit log. Every Console
-- action (ticket review, agent edit, manual publication, persona
-- change) lands here with actor, before/after snapshots and reason.
-- Insert + select only — no update/delete paths exist in code.
--
-- Rollback: DROP TABLE IF EXISTS nexus.console_audit;

CREATE TABLE IF NOT EXISTS nexus.console_audit (
    id          UUID PRIMARY KEY,
    actor       VARCHAR(64)  NOT NULL,
    action      VARCHAR(64)  NOT NULL,
    entity_type VARCHAR(32)  NOT NULL,
    entity_id   VARCHAR(64)  NOT NULL DEFAULT '',
    before      JSONB        NOT NULL DEFAULT '{}',
    after       JSONB        NOT NULL DEFAULT '{}',
    reason      VARCHAR(1024) NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ  NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_console_audit_created ON nexus.console_audit (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_console_audit_entity ON nexus.console_audit (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_console_audit_actor ON nexus.console_audit (actor, created_at DESC);
