-- +goose Up
-- +goose StatementBegin
--
-- Sprint 2 — Postgres-backed CompetitionRegistry.
--
-- Replaces the Sprint 1 permissive in-memory registry. Two tables:
--
--   competitions             — canonical competition records (UUID PK)
--   competition_external_ids — per-provider id mapping
--
-- The mapping table is what lets the same Brasileirão Série A live
-- under canonical UUID `c-uuid` with API-Football id "71" AND
-- football-data.org id "BSA" simultaneously. Adapters never see the
-- canonical UUID until the registry resolves their provider-native
-- id; the canonical UUID never leaves the Hub for the provider side.

CREATE TABLE competitions (
    id              UUID PRIMARY KEY,
    slug            VARCHAR(64)  NOT NULL UNIQUE,
    name            VARCHAR(128) NOT NULL,
    country_code    VARCHAR(8)   NOT NULL,
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_competitions_enabled ON competitions (enabled) WHERE enabled = TRUE;

CREATE TABLE competition_external_ids (
    id              BIGSERIAL    PRIMARY KEY,
    competition_id  UUID         NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    source_id       VARCHAR(64)  NOT NULL,  -- the adapter's SourceID
    external_id     VARCHAR(64)  NOT NULL,  -- provider-native id, e.g. "71"
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, external_id),
    UNIQUE (competition_id, source_id)
);
CREATE INDEX ix_competition_external_ids_competition ON competition_external_ids (competition_id);
CREATE INDEX ix_competition_external_ids_source ON competition_external_ids (source_id);

-- Seed — the 5 competitions Sprint 2 ships with.
-- UUIDs are stable hand-rolled values so local-lab + prod resolve
-- to the same canonical ids regardless of when the row was first
-- inserted (idempotent seeding).
INSERT INTO competitions (id, slug, name, country_code, enabled) VALUES
    ('c1a2b3c4-1111-4111-8111-000000000001', 'brasileirao_serie_a', 'Brasileirão Série A', 'BR', TRUE),
    ('c1a2b3c4-2222-4222-8222-000000000002', 'premier_league',      'Premier League',      'GB', TRUE),
    ('c1a2b3c4-3333-4333-8333-000000000003', 'champions_league',    'UEFA Champions League','EU', TRUE),
    ('c1a2b3c4-4444-4444-8444-000000000004', 'libertadores',        'Copa Libertadores',   'SA', TRUE),
    ('c1a2b3c4-5555-4555-8555-000000000005', 'la_liga',             'La Liga',             'ES', TRUE)
ON CONFLICT (id) DO NOTHING;

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS competition_external_ids;
DROP TABLE IF EXISTS competitions;
-- +goose StatementEnd
