-- Sprint 6.2 — cross-provider canonical match identity.
--
-- Resolves API-Football / Football-Data / The Odds API match
-- observations into a single canonical_match_id (competition + home +
-- away + kickoff, with a tolerance window). Provider-native ids are
-- preserved as aliases — never discarded.
--
-- ORM mappings: atlas.registry.models.CanonicalMatchRow / MatchAliasRow.
-- Fresh databases bootstrap via create_all() (sqlite/dev); production
-- runs this migration explicitly.
--
-- Idempotent: re-running on an already-migrated database is a no-op.

BEGIN;

CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.canonical_match (
    canonical_match_id  UUID         PRIMARY KEY,
    competition_id      UUID         NULL,
    home_team           VARCHAR(128) NOT NULL DEFAULT '',
    away_team           VARCHAR(128) NOT NULL DEFAULT '',
    kickoff             TIMESTAMPTZ  NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Shortlist key for the fuzzy (competition + teams) lookup; the kickoff
-- tolerance filter is applied after the shortlist.
CREATE INDEX IF NOT EXISTS ix_canonical_match_lookup
    ON atlas.canonical_match (competition_id, home_team, away_team);

CREATE TABLE IF NOT EXISTS atlas.match_alias (
    provider            VARCHAR(64)  NOT NULL,
    external_id         VARCHAR(128) NOT NULL,
    canonical_match_id  UUID         NOT NULL,
    linked_by           VARCHAR(16)  NOT NULL DEFAULT 'auto',
    linked_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, external_id)
);

-- Reverse lookup: all provider aliases for a canonical match.
CREATE INDEX IF NOT EXISTS ix_match_alias_canonical
    ON atlas.match_alias (canonical_match_id);

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.match_alias;
-- DROP TABLE IF EXISTS atlas.canonical_match;
-- COMMIT;
