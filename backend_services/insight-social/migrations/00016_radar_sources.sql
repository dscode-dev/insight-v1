-- +goose Up
-- +goose StatementBegin
--
-- RADAR-V1 — a registry of subscribed feeds, configured from the console.
--
-- Radar shows live matches, scores and match news. The platform owner's
-- instruction is that the structure be GENERIC and the services registrable:
-- api-key, names, configs, adjustable later. So this describes no provider in
-- particular — API-Football, a news API and an RSS bridge all fit the same
-- three columns plus `config`.
--
-- WHY jsonb FOR `config` AND NOT A COLUMN PER SETTING. Every provider asks for
-- different parameters — a competition filter here, a language there, a
-- polling interval somewhere else. A column per setting means a migration per
-- provider, which is exactly the coupling "generic" is meant to avoid. The
-- fields that are the same for ALL providers are columns; the rest is config.
--
CREATE TABLE IF NOT EXISTS radar_sources (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        VARCHAR(48)  NOT NULL UNIQUE,
    name        VARCHAR(120) NOT NULL,
    -- What the source produces, so Radar knows which surface it feeds.
    -- Constrained rather than free text: an unrecognised kind means the
    -- records arrive and nothing renders them, which reads as "the provider
    -- is down" and is not.
    kind        VARCHAR(24)  NOT NULL,
    base_url    TEXT         NOT NULL,

    -- THE KEY IS WRITE-ONLY, and this column is never selected by any read
    -- path. An API key management screen that echoes the key back turns every
    -- console session, log line and screenshot into a place the credential can
    -- leak from; the operator already has it, and what they need to see is
    -- WHETHER one is set, not what it is.
    --
    -- Stored as given, not encrypted, and that is a deliberate half-measure:
    -- the database is not readable from outside the VM and the column is not
    -- exposed, but anyone with database access can read it. Column-level
    -- encryption (pgcrypto, key outside the database) is the next step and is
    -- recorded as such rather than assumed done.
    api_key     TEXT,
    -- Shown instead of the key: enough for an operator to recognise WHICH key
    -- is configured without the value being recoverable from it.
    api_key_hint VARCHAR(8),

    config      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    -- How often to poll, in seconds. A column because every provider has one
    -- and Radar's scheduler must read it without knowing the provider.
    poll_seconds INTEGER     NOT NULL DEFAULT 300,
    active      BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Providers that need no credential (a public RSS feed) are registered
    -- with this FALSE, so the key requirement below does not block them.
    requires_key BOOLEAN     NOT NULL DEFAULT TRUE,

    -- Operational truth, written by the collector, not the console. An
    -- operator debugging "why is Radar empty" needs to see whether the last
    -- attempt worked, and a registry that only holds intent cannot say.
    last_success_at TIMESTAMPTZ,
    last_error_at   TIMESTAMPTZ,
    last_error      TEXT,

    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_by  TEXT,

    CONSTRAINT radar_sources_kind_check
        CHECK (kind IN ('live_matches', 'scores', 'news', 'odds', 'other')),
    CONSTRAINT radar_sources_poll_check
        CHECK (poll_seconds BETWEEN 10 AND 86400),
    -- A source registered as active with no key would fail on every poll and
    -- fill the error column with the same message.
    CONSTRAINT radar_sources_key_when_required_check
        CHECK (NOT active OR NOT requires_key OR api_key IS NOT NULL)
);

-- The scheduler's query: which sources are due.
CREATE INDEX IF NOT EXISTS ix_radar_sources_active
    ON radar_sources (active, poll_seconds) WHERE active;

-- ---------------------------------------------------------------------------
-- What the sources produce.
--
-- ONE TABLE FOR EVERY KIND, for the same reason `config` is jsonb: Radar
-- renders a stream, and a table per provider would make "the last twenty
-- things that happened" a union that grows with every subscription.
--
-- `external_id` + `source_id` is the natural key. Providers re-send the same
-- item on every poll — that is normal, not an error — and without a unique
-- key each poll would duplicate the entire window.
CREATE TABLE IF NOT EXISTS radar_items (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID        NOT NULL REFERENCES radar_sources(id) ON DELETE CASCADE,
    external_id VARCHAR(128) NOT NULL,
    kind        VARCHAR(24) NOT NULL,
    title       TEXT        NOT NULL,
    summary     TEXT,
    url         TEXT,
    image_url   TEXT,
    -- The provider's own payload, kept whole. When a field turns out to matter
    -- later it is already here, instead of needing a backfill nobody can do
    -- because the provider only serves a rolling window.
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,

    -- The competition this item belongs to, when it maps to one. Radar is
    -- filtered by the same rail as the feed.
    competition_id UUID     REFERENCES competitions(id) ON DELETE SET NULL,

    -- When the PROVIDER says it happened, which is what the reader cares
    -- about — not when we happened to fetch it.
    occurred_at TIMESTAMPTZ NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT radar_items_unique_per_source UNIQUE (source_id, external_id)
);

-- ON DELETE SET NULL on the competition, not RESTRICT: a radar item is
-- external content that merely mentions a competition. Blocking a competition
-- from being retired because a news article referenced it would be the
-- registry serving the feed instead of the other way round.

-- Radar's read: newest first, optionally one competition, optionally one kind.
CREATE INDEX IF NOT EXISTS ix_radar_items_recent
    ON radar_items (occurred_at DESC, kind);
CREATE INDEX IF NOT EXISTS ix_radar_items_competition
    ON radar_items (competition_id, occurred_at DESC)
    WHERE competition_id IS NOT NULL;

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS radar_items;
DROP TABLE IF EXISTS radar_sources;
-- +goose StatementEnd
