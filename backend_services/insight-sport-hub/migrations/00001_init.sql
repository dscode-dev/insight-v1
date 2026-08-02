-- +goose Up
-- +goose StatementBegin
--
-- Sprint 1 — Insight Sports Data Hub foundation.
--
-- Five tables, all designed around two non-negotiable architectural
-- rules:
--
--   1. Lineage preservation: every Raw and every Canonical event
--      stores the COMPLETE SourceRef object as JSONB. Convenience
--      columns (source_id, source_type) are projections for indexed
--      queries — they MUST agree with the JSONB blob (write path
--      enforces by using the same SourceRef for both writes).
--
--   2. Natural identity for canonical events: (sport, competition_id,
--      match_id, event_type) is UNIQUE. Upserts conflict-resolve on
--      this tuple so multiple raws for the same identity merge
--      idempotently into one canonical row.
--
-- Schema lives in the default `insight_sports_hub` database.

-- ---------- sources ----------
CREATE TABLE sources (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(128) NOT NULL UNIQUE,
    type                VARCHAR(32)  NOT NULL,
    priority            INTEGER      NOT NULL DEFAULT 100,
    enabled             BOOLEAN      NOT NULL DEFAULT TRUE,
    confidence_weight   NUMERIC(5,4) NOT NULL DEFAULT 1.0,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CHECK (priority >= 0),
    CHECK (confidence_weight >= 0 AND confidence_weight <= 1),
    -- Allow-list of source types — mirrors the Go SourceType enum
    -- byte-for-byte. ALTER this constraint when adding a new type
    -- (additive-only) AND update the Go enum in lock-step.
    CHECK (type IN (
        'official_api', 'commercial_api', 'official_club', 'official_league',
        'trusted_media', 'internal_bot', 'community', 'unknown'
    ))
);
CREATE INDEX ix_sources_type ON sources (type);
CREATE INDEX ix_sources_enabled ON sources (enabled) WHERE enabled = TRUE;

-- ---------- raw_sports_events ----------
--
-- Write-once log. The `source` JSONB column carries the full
-- SourceRef — never truncate or project. `source_id`/`source_type`
-- exist only to support indexed queries; the write path writes both
-- from the same SourceRef so drift is impossible.
--
-- Sport column is locked to 'football' via CHECK constraint — V1
-- scope. Additive-only: future migrations append to the IN clause.
CREATE TABLE raw_sports_events (
    raw_event_id        UUID PRIMARY KEY,
    source              JSONB        NOT NULL,
    source_id           VARCHAR(64)  NOT NULL,
    source_type         VARCHAR(32)  NOT NULL,
    sport               VARCHAR(24)  NOT NULL,
    competition_id      UUID         NOT NULL,
    external_match_id   VARCHAR(128) NOT NULL,
    event_type          VARCHAR(64)  NOT NULL,
    observed_at         TIMESTAMPTZ  NOT NULL,
    payload             JSONB        NOT NULL,
    raw_confidence      NUMERIC(5,4) NOT NULL,
    ingested_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CHECK (raw_confidence >= 0 AND raw_confidence <= 1),
    CHECK (sport IN ('football')),
    CHECK (payload IS NOT NULL AND jsonb_typeof(payload) IN ('object', 'array'))
);
CREATE INDEX ix_raw_events_external_match ON raw_sports_events (external_match_id);
CREATE INDEX ix_raw_events_observed_at    ON raw_sports_events (observed_at DESC);
CREATE INDEX ix_raw_events_source_id      ON raw_sports_events (source_id);
CREATE INDEX ix_raw_events_event_type     ON raw_sports_events (event_type);
CREATE INDEX ix_raw_events_competition    ON raw_sports_events (competition_id);

-- ---------- canonical_sports_events ----------
--
-- Platform truth. The UNIQUE on the 4-tuple drives the ON CONFLICT
-- DO UPDATE in the upsert path. season is nullable because back-fill
-- payloads + early ingestion may not carry it (Sprint 2 fills via
-- the match catalogue).
CREATE TABLE canonical_sports_events (
    event_id            UUID PRIMARY KEY,
    sport               VARCHAR(24)  NOT NULL,
    competition_id      UUID         NOT NULL,
    season              VARCHAR(16),
    match_id            UUID         NOT NULL,
    event_type          VARCHAR(64)  NOT NULL,
    status              VARCHAR(16)  NOT NULL,
    confidence          NUMERIC(5,4) NOT NULL,
    sources             JSONB        NOT NULL,
    occurred_at         TIMESTAMPTZ  NOT NULL,
    payload             JSONB        NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CHECK (confidence >= 0 AND confidence <= 1),
    CHECK (status IN ('candidate', 'confirmed', 'conflicting', 'rejected', 'stale')),
    CHECK (sport IN ('football')),
    CHECK (payload IS NOT NULL AND jsonb_typeof(payload) IN ('object', 'array')),
    CHECK (sources IS NOT NULL AND jsonb_typeof(sources) = 'array'),
    UNIQUE (sport, competition_id, match_id, event_type)
);
CREATE INDEX ix_canonical_events_match_id    ON canonical_sports_events (match_id);
CREATE INDEX ix_canonical_events_status      ON canonical_sports_events (status);
CREATE INDEX ix_canonical_events_occurred_at ON canonical_sports_events (occurred_at DESC);
CREATE INDEX ix_canonical_events_competition ON canonical_sports_events (competition_id);

-- ---------- event_lineage ----------
--
-- Many-to-many: one raw can contribute to several canonicals (rare
-- but legal); every canonical has ≥1 raw (architectural rule).
-- Cascade on canonical delete (the canonical was wrong and was
-- archived — the lineage rows are noise). RESTRICT on raw delete:
-- raw events are immutable + must never be deleted without an audit
-- trail, which deleting via cascade would bypass.
CREATE TABLE event_lineage (
    id                  BIGSERIAL    PRIMARY KEY,
    canonical_event_id  UUID         NOT NULL REFERENCES canonical_sports_events(event_id) ON DELETE CASCADE,
    raw_event_id        UUID         NOT NULL REFERENCES raw_sports_events(raw_event_id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (canonical_event_id, raw_event_id)
);
CREATE INDEX ix_event_lineage_canonical ON event_lineage (canonical_event_id);
CREATE INDEX ix_event_lineage_raw       ON event_lineage (raw_event_id);

-- ---------- source_relationships ----------
--
-- Read-optimised projection of "which canonical events did this
-- source contribute to". The authoritative lineage lives in
-- canonical_sports_events.sources (JSONB array) — this table is a
-- denormalised projection populated by the same write path so admin
-- dashboards can answer "show me every event api_football touched
-- this week" without scanning every canonical row's JSONB.
--
-- Population is the application's responsibility — Sprint 1 ships
-- the table; Sprint 2 wires the trigger or background projector
-- once the access pattern is confirmed.
CREATE TABLE source_relationships (
    id                      BIGSERIAL    PRIMARY KEY,
    canonical_event_id      UUID         NOT NULL REFERENCES canonical_sports_events(event_id) ON DELETE CASCADE,
    source_id               VARCHAR(64)  NOT NULL,
    source_type             VARCHAR(32)  NOT NULL,
    contribution_confidence NUMERIC(5,4) NOT NULL,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CHECK (contribution_confidence >= 0 AND contribution_confidence <= 1)
);
CREATE INDEX ix_source_relationships_source_id ON source_relationships (source_id);
CREATE INDEX ix_source_relationships_canonical ON source_relationships (canonical_event_id);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS source_relationships;
DROP TABLE IF EXISTS event_lineage;
DROP TABLE IF EXISTS canonical_sports_events;
DROP TABLE IF EXISTS raw_sports_events;
DROP TABLE IF EXISTS sources;
-- +goose StatementEnd
