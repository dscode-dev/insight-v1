-- Durable record of human approve/reject on a Quality Gate replay.
--
-- Context: ATLAS_V1_FROZEN.md requires that every new detector or
-- heuristic pass the Quality Gate (regression + promotion) against the
-- frozen baseline before promotion, and states plainly that "Human
-- approval remains mandatory". That mandate had no implementation:
-- `atlas/backtest/quality.py` produced per-detector recommendations
-- (Approved / Warning / Rejected) that no code path consumed, and
-- nothing anywhere in the service recorded that a person had reviewed
-- or signed off on a replay. A mandate with no durable decision record
-- is unauditable — there is no way to answer "who approved this, when,
-- against which baseline, and did they override the gate?".
--
-- Identity is `replay_hash`, not `execution_id`, on purpose:
-- `ReplayService` holds executions/quality/manifests in ordinary
-- in-process dicts, so an execution id stops resolving as soon as the
-- process restarts. The deterministic replay fingerprint identifies
-- the exact evaluated behaviour permanently, which is what a decision
-- is actually about.
--
-- Safe on an existing database: new table only, no writes to or reads
-- from anything that already exists.
--
-- Idempotent: every statement is IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS atlas.promotion_decisions (
    id                      UUID PRIMARY KEY,
    replay_hash             VARCHAR(128)  NOT NULL,
    execution_id            VARCHAR(64)   NOT NULL DEFAULT '',
    baseline_hash           VARCHAR(128),
    verdict                 VARCHAR(16)   NOT NULL,
    decided_by              VARCHAR(128)  NOT NULL,
    reason                  TEXT          NOT NULL,
    overrode_recommendation BOOLEAN       NOT NULL DEFAULT FALSE,
    without_baseline        BOOLEAN       NOT NULL DEFAULT FALSE,
    quality_regression      BOOLEAN       NOT NULL DEFAULT FALSE,
    recommendation          JSONB         NOT NULL DEFAULT '{}'::jsonb,
    decided_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT ck_promotion_decisions_verdict
        CHECK (verdict IN ('approved', 'rejected')),
    -- An approval must carry a justification. The gate's own
    -- recommendation is not a substitute for the human's reasoning,
    -- especially in the override case.
    CONSTRAINT ck_promotion_decisions_reason
        CHECK (length(btrim(reason)) > 0)
);

-- One standing decision per evaluated behaviour: the same code over the
-- same data produces the same hash, so a second row for it is either a
-- duplicate submit or a contradiction. Both should fail loudly.
CREATE UNIQUE INDEX IF NOT EXISTS ux_promotion_decisions_replay_hash
    ON atlas.promotion_decisions (replay_hash);

CREATE INDEX IF NOT EXISTS ix_promotion_decisions_decided_at
    ON atlas.promotion_decisions (decided_at DESC);

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.promotion_decisions;
-- COMMIT;
