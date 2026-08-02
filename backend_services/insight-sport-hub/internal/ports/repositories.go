// Package ports declares every interface the application layer
// depends on. Adapters implement them; the application layer NEVER
// imports an adapter package — that's the hexagonal architecture
// rule the boundary tests enforce.
//
// Repository ports return domain types and accept domain types.
// Error semantics are uniform: not-found surfaces as a typed
// sentinel error (ErrNotFound below) so application services can
// distinguish "absent" from "infrastructure failure" without
// pattern-matching on driver-specific exceptions.
package ports

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/lineage"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
)

// ErrNotFound is the canonical "row missing" sentinel every repo
// returns. Application services check via errors.Is so the concrete
// repo can wrap it with additional context if useful.
var ErrNotFound = errors.New("ports: not found")

// ErrDuplicate signals an insert conflict — duplicate primary key
// or unique constraint violation. Distinct from arbitrary infra
// failures so the orchestrator can short-circuit re-ingestion of
// already-seen raw events without retrying.
var ErrDuplicate = errors.New("ports: duplicate")

// ---------------------------------------------------------------------------
// SourceRepository — registered Source aggregates.
// ---------------------------------------------------------------------------

type SourceRepository interface {
	Insert(ctx context.Context, s *source.Source) error
	GetByID(ctx context.Context, id uuid.UUID) (*source.Source, error)
	GetByName(ctx context.Context, name string) (*source.Source, error)
	// List returns every registered source ordered by Priority asc, then
	// Name asc. Disabled sources are included — callers filter as needed.
	List(ctx context.Context) ([]*source.Source, error)
	Update(ctx context.Context, s *source.Source) error
}

// ---------------------------------------------------------------------------
// RawEventRepository — write-once log of raw observations.
// ---------------------------------------------------------------------------

type RawEventRepository interface {
	// Insert persists a new raw event. Returns ErrDuplicate when the
	// raw_event_id already exists — the orchestrator uses this to
	// detect re-ingestion of the same observation.
	Insert(ctx context.Context, raw *event.RawSportsEvent) error
	GetByID(ctx context.Context, id uuid.UUID) (*event.RawSportsEvent, error)
	// ListForIdentity returns every raw event whose Identity matches
	// the supplied canonical natural key. Used by the canonicalisation
	// + conflict detection services.
	ListForIdentity(ctx context.Context, id event.Identity) ([]*event.RawSportsEvent, error)
	// ExistsByID is a cheap (no scan) duplicate-check helper.
	ExistsByID(ctx context.Context, id uuid.UUID) (bool, error)
}

// ---------------------------------------------------------------------------
// CanonicalEventRepository — the platform-truth aggregate store.
// ---------------------------------------------------------------------------

type CanonicalEventRepository interface {
	// Upsert inserts a new canonical or updates an existing one based
	// on Identity. The natural key (sport, competition, match, type)
	// is enforced UNIQUE at the schema level — upsert collapses to
	// INSERT ... ON CONFLICT (identity_cols) DO UPDATE.
	Upsert(ctx context.Context, c *event.CanonicalSportsEvent) error
	GetByID(ctx context.Context, id uuid.UUID) (*event.CanonicalSportsEvent, error)
	// GetByIdentity is the duplicate-canonical check + the
	// canonicalisation service's "do we already have a row for this?"
	// lookup. Returns ErrNotFound when absent.
	GetByIdentity(ctx context.Context, id event.Identity) (*event.CanonicalSportsEvent, error)
}

// ---------------------------------------------------------------------------
// LineageRepository — Raw → Canonical link rows.
// ---------------------------------------------------------------------------

type LineageRepository interface {
	// Link records a new raw → canonical contribution. Idempotent on
	// (canonical_event_id, raw_event_id) per the UNIQUE constraint.
	Link(ctx context.Context, canonicalID, rawID uuid.UUID) error
	// GraphFor returns the full lineage of a canonical event — used by
	// the future admin dashboard. Empty result on unknown canonical.
	GraphFor(ctx context.Context, canonicalID uuid.UUID) (lineage.Graph, error)
	// LinksFor returns the raw → canonical link rows for a given raw
	// event (rare query: "which canonicals consumed this raw?").
	LinksFor(ctx context.Context, rawID uuid.UUID) ([]lineage.Link, error)
}

// ---------------------------------------------------------------------------
// CompetitionRegistry — vetted set of competition ids the Hub accepts.
// ---------------------------------------------------------------------------

// Sprint 1 shipped an in-memory permissive registry. Sprint 2
// extends the interface for the Postgres-backed implementation +
// provider→canonical mapping. The legacy in-memory adapter still
// satisfies the contract (the new methods return empty/no-op).
type CompetitionRegistry interface {
	// IsKnown — fast yes/no for the validation hot path.
	IsKnown(ctx context.Context, competitionID uuid.UUID) (bool, error)

	// Register persists a fresh competition. Returns ErrDuplicate
	// when slug collides.
	Register(ctx context.Context, c Competition) error

	// Lookup fetches a competition by its canonical UUID.
	Lookup(ctx context.Context, id uuid.UUID) (Competition, error)

	// LookupByExternalID resolves a provider-native id to the Hub's
	// canonical competition. Adapters call this internally to map
	// inbound payloads.
	LookupByExternalID(ctx context.Context, sourceID, externalID string) (Competition, error)

	// LinkExternalID adds a provider→canonical mapping. Idempotent
	// on (source_id, external_id).
	LinkExternalID(ctx context.Context, competitionID uuid.UUID, sourceID, externalID string) error

	// GetExternalIDForSource — the INVERSE of LookupByExternalID.
	// Given the Hub's canonical UUID + a provider's source_id,
	// return that provider's native id for the competition. Used
	// by adapter.FetchFixtures/FetchStandings to translate the
	// Hub's request into a provider call. ErrNotFound when no
	// mapping exists for this (canonical, source) pair.
	GetExternalIDForSource(ctx context.Context, competitionID uuid.UUID, sourceID string) (string, error)

	// SetEnabled flips a competition on/off. Disabled competitions
	// are rejected by IsKnown.
	SetEnabled(ctx context.Context, id uuid.UUID, enabled bool) error

	// List returns every registered competition (enabled or not).
	// Admin tooling uses this.
	List(ctx context.Context) ([]Competition, error)
}

// Competition is the read-model returned by the registry. Lives
// in ports rather than domain because it's a registry-only concept
// — events carry only the canonical UUID + slug.
type Competition struct {
	ID          uuid.UUID
	Slug        string
	Name        string
	CountryCode string
	Enabled     bool
}
