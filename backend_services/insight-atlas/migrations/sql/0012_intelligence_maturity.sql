-- 0012 — Intelligence Maturity (Sprint 1.5).
--
-- trend_outcomes: append-only log of closed trend lifecycle instances
-- (insert-once by instance_id; replay-safe). Every market-memory,
-- historical-outcome and continuation profile aggregates over it.
--
-- competition_regimes: append-only regime classification history; the
-- latest row per competition is the current regime.
--
-- Rollback:
--   DROP TABLE IF EXISTS atlas.trend_outcomes;
--   DROP TABLE IF EXISTS atlas.competition_regimes;

CREATE TABLE IF NOT EXISTS atlas.trend_outcomes (
    instance_id        UUID PRIMARY KEY,
    canonical_match_id UUID NOT NULL,
    competition_id     UUID NULL,
    trend_type         VARCHAR(48) NOT NULL,
    direction          INTEGER NOT NULL DEFAULT 0,
    outcome            VARCHAR(16) NOT NULL,
    duration_seconds   DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_confidence     DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_strength       DOUBLE PRECISION NOT NULL DEFAULT 0,
    observation_count  INTEGER NOT NULL DEFAULT 0,
    home_team          VARCHAR(128) NOT NULL DEFAULT '',
    away_team          VARCHAR(128) NOT NULL DEFAULT '',
    closed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_trend_outcomes_type_comp
    ON atlas.trend_outcomes (trend_type, competition_id);
CREATE INDEX IF NOT EXISTS ix_trend_outcomes_closed
    ON atlas.trend_outcomes (closed_at);
CREATE INDEX IF NOT EXISTS ix_trend_outcomes_match
    ON atlas.trend_outcomes (canonical_match_id);

CREATE TABLE IF NOT EXISTS atlas.competition_regimes (
    id             UUID PRIMARY KEY,
    competition_id UUID NOT NULL,
    regime         VARCHAR(24) NOT NULL,
    profile        JSONB NOT NULL DEFAULT '{}',
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_competition_regimes_comp
    ON atlas.competition_regimes (competition_id, computed_at);
