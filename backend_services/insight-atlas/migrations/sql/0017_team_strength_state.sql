-- Atlas Similarity Robustness — live team-strength state.
--
-- Context: the similarity engine (atlas.intelligence.similarity_engine)
-- historically only carried 7 signals with no live team-strength math
-- anywhere in the request path (Elo/attack-defense/h2h/standings only
-- ever ran in offline, disconnected `atlas/outcome/` training scripts).
-- This migration adds the persistent state a live, incrementally-updated
-- team-strength engine needs (atlas/strength/) so live requests get an
-- O(1) lookup instead of replaying history per request.
--
-- Source of truth for match RESULTS is Explorer's validated fixture lake
-- (the same source `atlas/outcome/train.py` and
-- `atlas/intelligence/historical.py::load_dataset` already trust) — NOT
-- the live canonical-event stream, which only carries in-play signals
-- (odds, stats, risk) and never a structured final-score fact. A
-- watcher-style periodic sync (matching the atlas/watchers/ pattern,
-- e.g. ClusterJanitor) keeps this state current; `strength_processed_matches`
-- makes that sync idempotent/replay-safe the same way `odds_ticks` uses
-- `canonical_event_id`.
--
-- Idempotent: every statement is guarded so re-running on an
-- already-migrated database is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS atlas;

-- Global per-team rating state (Elo is not competition-scoped — a team
-- carries one rating across competitions, same convention as
-- HistoricalProjectionV3's in-memory `_elo` dict).
CREATE TABLE IF NOT EXISTS atlas.team_strength_state (
    team                VARCHAR(128)     PRIMARY KEY,
    elo                 DOUBLE PRECISION NOT NULL DEFAULT 1500.0,
    venue_elo_home      DOUBLE PRECISION NOT NULL DEFAULT 1500.0,
    venue_elo_away      DOUBLE PRECISION NOT NULL DEFAULT 1500.0,
    -- Rolling last-10 {gf, ga} results, most recent last. Small and
    -- bounded — a JSONB list, not a child table.
    rolling_window      JSONB            NOT NULL DEFAULT '[]'::jsonb,
    last_match_at       TIMESTAMPTZ      NULL,
    updated_at          TIMESTAMPTZ      NOT NULL DEFAULT now()
);

-- Per-(competition, season) standings — points/goal-difference are only
-- meaningful within one competition's table.
CREATE TABLE IF NOT EXISTS atlas.team_standings_state (
    competition      VARCHAR(128)     NOT NULL,
    season           VARCHAR(32)      NOT NULL,
    team             VARCHAR(128)     NOT NULL,
    points           INTEGER          NOT NULL DEFAULT 0,
    goal_difference  INTEGER          NOT NULL DEFAULT 0,
    matches_played   INTEGER          NOT NULL DEFAULT 0,
    updated_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (competition, season, team)
);

CREATE INDEX IF NOT EXISTS ix_team_standings_state_table
    ON atlas.team_standings_state (competition, season, points DESC, goal_difference DESC);

-- Per-(competition, season) league scoring rate, used to normalize
-- attack/defense strength (goals-for/against relative to the league's
-- own average, not an absolute count).
CREATE TABLE IF NOT EXISTS atlas.competition_season_state (
    competition       VARCHAR(128)     NOT NULL,
    season            VARCHAR(32)      NOT NULL,
    goal_sum          BIGINT           NOT NULL DEFAULT 0,
    team_match_count  BIGINT           NOT NULL DEFAULT 0,
    updated_at        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (competition, season)
);

-- Head-to-head counters, keyed by a CANONICALLY ORDERED team pair
-- (team_a < team_b lexicographically) so a lookup is direction-agnostic;
-- the caller maps team_a_wins/team_b_wins onto home/away at query time.
CREATE TABLE IF NOT EXISTS atlas.head_to_head_state (
    team_a        VARCHAR(128)     NOT NULL,
    team_b        VARCHAR(128)     NOT NULL,
    team_a_wins   INTEGER          NOT NULL DEFAULT 0,
    team_b_wins   INTEGER          NOT NULL DEFAULT 0,
    draws         INTEGER          NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (team_a, team_b),
    CONSTRAINT ck_head_to_head_state_ordered CHECK (team_a < team_b)
);

-- Idempotency ledger for the strength-sync watcher: one row per
-- Explorer match uid already folded into the state above. Re-processing
-- (a re-run, a watcher restart) is a no-op skip, same role
-- `odds_ticks.canonical_event_id` plays for the odds pipeline.
CREATE TABLE IF NOT EXISTS atlas.strength_processed_matches (
    match_uid     TEXT             PRIMARY KEY,
    processed_at  TIMESTAMPTZ      NOT NULL DEFAULT now()
);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.strength_processed_matches;
-- DROP TABLE IF EXISTS atlas.head_to_head_state;
-- DROP TABLE IF EXISTS atlas.competition_season_state;
-- DROP TABLE IF EXISTS atlas.team_standings_state;
-- DROP TABLE IF EXISTS atlas.team_strength_state;
-- COMMIT;
