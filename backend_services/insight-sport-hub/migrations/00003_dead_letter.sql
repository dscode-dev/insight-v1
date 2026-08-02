-- +goose Up
-- +goose StatementBegin
--
-- Sprint 5.1 — Dead Letter Store
--
-- Captures terminal SyncJob failures (validation, permanent, attempts
-- exhausted) so operators can inspect them in /v1/dlq, replay
-- selectively, or aggregate failure rates per provider.
--
-- Schema rules:
--   * job_id is a UUIDv4 (NOT the canonical event id) — matches
--     `syncdom.JobID`.
--   * Failures are append-only. A replay creates a NEW SyncJob
--     downstream; this row remains intact for audit.
--   * `failure_type` and `reason` are STRING enums; we keep them as
--     plain text + indexes so additive evolution (new bands, new
--     reason slugs) doesn't require a migration.
CREATE TABLE IF NOT EXISTS dead_letter_failures (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL,
    provider_id     TEXT NOT NULL,
    competition_id  UUID NOT NULL,
    sync_type       TEXT NOT NULL,
    reason          TEXT NOT NULL,
    failure_type    TEXT NOT NULL,
    attempts        INTEGER NOT NULL,
    failed_at       TIMESTAMPTZ NOT NULL,
    replayed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS dead_letter_failures_provider_idx
    ON dead_letter_failures (provider_id);

CREATE INDEX IF NOT EXISTS dead_letter_failures_failed_at_idx
    ON dead_letter_failures (failed_at DESC);

CREATE INDEX IF NOT EXISTS dead_letter_failures_failure_type_idx
    ON dead_letter_failures (failure_type);

-- For "show me the unreplayed failures" — common admin query.
CREATE INDEX IF NOT EXISTS dead_letter_failures_unreplayed_idx
    ON dead_letter_failures (failed_at DESC)
    WHERE replayed_at IS NULL;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS dead_letter_failures;
-- +goose StatementEnd
