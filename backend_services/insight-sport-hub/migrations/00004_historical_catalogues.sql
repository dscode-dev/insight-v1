-- +goose Up
-- +goose StatementBegin
--
-- ML-1 — Historical catalogue foundation.
--
-- Additive schema for canonical historical identity resolution. The hot
-- canonical event contract remains unchanged; these catalogues provide the
-- durable target for backfill/import jobs so provider-native match ids never
-- create duplicate historical matches.

CREATE TABLE IF NOT EXISTS teams (
    id              UUID PRIMARY KEY,
    slug            VARCHAR(96)  NOT NULL UNIQUE,
    name            VARCHAR(128) NOT NULL,
    country_code    VARCHAR(8),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_teams_country ON teams (country_code);

CREATE TABLE IF NOT EXISTS team_external_ids (
    id              BIGSERIAL    PRIMARY KEY,
    team_id         UUID         NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    source_id       VARCHAR(64)  NOT NULL,
    external_id     VARCHAR(128) NOT NULL,
    first_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_id, external_id),
    UNIQUE (team_id, source_id)
);
CREATE INDEX IF NOT EXISTS ix_team_external_ids_team ON team_external_ids (team_id);

CREATE TABLE IF NOT EXISTS matches (
    id              UUID PRIMARY KEY,
    sport           VARCHAR(24)  NOT NULL DEFAULT 'football',
    competition_id  UUID         NOT NULL REFERENCES competitions(id) ON DELETE RESTRICT,
    season          VARCHAR(16),
    home_team_id    UUID         NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    away_team_id    UUID         NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
    kickoff_at      TIMESTAMPTZ  NOT NULL,
    status          VARCHAR(32)  NOT NULL DEFAULT 'scheduled',
    metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CHECK (sport IN ('football')),
    CHECK (home_team_id <> away_team_id),
    UNIQUE (sport, competition_id, kickoff_at, home_team_id, away_team_id)
);
CREATE INDEX IF NOT EXISTS ix_matches_competition_kickoff ON matches (competition_id, kickoff_at);
CREATE INDEX IF NOT EXISTS ix_matches_home_team ON matches (home_team_id);
CREATE INDEX IF NOT EXISTS ix_matches_away_team ON matches (away_team_id);

CREATE TABLE IF NOT EXISTS match_external_ids (
    id              BIGSERIAL    PRIMARY KEY,
    match_id        UUID         NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    source_id       VARCHAR(64)  NOT NULL,
    external_id     VARCHAR(128) NOT NULL,
    first_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_id, external_id),
    UNIQUE (match_id, source_id)
);
CREATE INDEX IF NOT EXISTS ix_match_external_ids_match ON match_external_ids (match_id);

CREATE TABLE IF NOT EXISTS historical_import_runs (
    id                  UUID PRIMARY KEY,
    source_id           VARCHAR(64) NOT NULL,
    sport               VARCHAR(24) NOT NULL DEFAULT 'football',
    window_start        TIMESTAMPTZ NOT NULL,
    window_end          TIMESTAMPTZ NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'running',
    imported_matches    INTEGER     NOT NULL DEFAULT 0,
    imported_events     INTEGER     NOT NULL DEFAULT 0,
    provider_metadata   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    CHECK (sport IN ('football')),
    CHECK (window_start < window_end),
    CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS ix_historical_import_runs_source
    ON historical_import_runs (source_id, started_at DESC);

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS historical_import_runs;
DROP TABLE IF EXISTS match_external_ids;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS team_external_ids;
DROP TABLE IF EXISTS teams;
-- +goose StatementEnd
