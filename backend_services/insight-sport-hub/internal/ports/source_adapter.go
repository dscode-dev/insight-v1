// SourceAdapter — Sprint 2.
//
// The interface every provider adapter implements. The Hub's
// application layer calls only these methods; the rest of the
// adapter (HTTP client, DTOs, mappers, retry/timeouts) is the
// adapter's private implementation detail.
//
// Critical architectural rule (Sprint 2 spec): adapters are
// stateless translators. They MUST NOT import application packages
// (normalization/validation/conflict/confidence/canonicalization).
// They MAY import:
//   - internal/domain/**   — pure types
//   - internal/ports       — this file + sibling port interfaces
//
// The boundary test in tests/application/boundary_test.go enforces
// this — adding an import from any adapter to internal/application
// fails the suite.
package ports

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

// SourceAdapter is the contract between the Hub orchestrator and
// each provider integration.
//
// Adapters return already-built `*event.RawSportsEvent` values
// (with the full SourceRef embedded). The orchestrator runs every
// raw through the rest of the pipeline (validation → conflict →
// confidence → canonical upsert → publish) — the adapter NEVER
// does any of that itself.
type SourceAdapter interface {
	// Identity describes which Source this adapter represents.
	// Stable for the lifetime of the process — read once at startup
	// to register the Source aggregate.
	Identity() AdapterIdentity

	// FetchCompetitions returns every competition the provider can
	// serve. Used at startup + on-demand by ops tooling to populate
	// the CompetitionRegistry. Does NOT produce RawSportsEvents —
	// competitions are reference data, not events.
	FetchCompetitions(ctx context.Context) ([]CompetitionDescriptor, error)

	// FetchFixtures returns upcoming + recent fixtures for the
	// requested competition+season. Each fixture is converted to a
	// RawSportsEvent with event_type either "match.fixture" (not yet
	// started) or "match.result" (finished). The mapper decides the
	// event_type from the upstream status field.
	FetchFixtures(ctx context.Context, req FixtureFetchRequest) ([]*event.RawSportsEvent, error)

	// FetchStandings returns the current league table for the
	// requested competition+season as a SINGLE RawSportsEvent of
	// type "competition.standings". The payload carries the full
	// table; consumers parse it (the Hub is provider-agnostic at
	// the row level).
	FetchStandings(ctx context.Context, req StandingsFetchRequest) ([]*event.RawSportsEvent, error)

	// Health returns the adapter's most recent operational snapshot.
	// Stateless adapters delegate to the observability subsystem —
	// this method exists on the interface so the HTTP /providers/status
	// route can polymorphically query every adapter without knowing
	// the concrete type.
	Health() HealthSnapshot
}

// AdapterIdentity is the static descriptor of one adapter. Mirrors
// the data needed to register a `source.Source` aggregate +
// populate the `SourceRef.AdapterVersion` field on every emitted
// raw event.
type AdapterIdentity struct {
	// SourceID — canonical id used as the SourceRef.SourceID on
	// every raw event this adapter produces. Conventionally the
	// provider's short slug ("api_football", "football_data").
	SourceID string

	// SourceName — human-friendly label for the registry + UI.
	SourceName string

	// SourceType — almost always commercial_api in Sprint 2.
	// Internal-bot adapters (Sprint 3+) set internal_bot.
	SourceType source.SourceType

	// AdapterVersion — "{slug}@{semver}" form, e.g. "api_football@1.0.0".
	// Lands on SourceRef.AdapterVersion verbatim.
	AdapterVersion string

	// APIVersion — provider's API version when available
	// (e.g. "v3" for API-Football, "v4" for football-data.org).
	// Captured in SourceRef.Metadata so debugging can pin the
	// upstream surface that produced any given event.
	APIVersion string

	// DefaultConfidence — the per-event confidence the adapter
	// stamps on every SourceRef when the provider doesn't supply a
	// per-event quality signal. Conservative default ~0.85.
	DefaultConfidence float64

	// ConfidenceWeight — the Source aggregate's static trust
	// multiplier used by the WeightedAveragePolicy. Different from
	// DefaultConfidence: this is the long-lived reputation of the
	// provider; the other is the per-event quality.
	ConfidenceWeight float64

	// Capabilities — Sprint 2.1. Declares which data classes the
	// adapter can serve. Read by the future Scheduler (Sprint 3) to
	// avoid issuing requests the provider would 404; surfaced via the
	// /v1/providers/status endpoint for admin tooling.
	Capabilities source.ProviderCapability
}

// CompetitionDescriptor describes one competition the provider can
// serve. Used to populate the CompetitionRegistry — NOT to produce
// events. Pure reference data.
type CompetitionDescriptor struct {
	// ExternalID is the provider-native id (e.g. "71" for API-Football
	// Brasileirão Série A). NEVER escapes the adapter — the
	// CompetitionRegistry stores its own canonical uuid.UUID and
	// maps provider→canonical inside the persistence layer.
	ExternalID string

	// Name as the provider names it (e.g. "Premier League").
	Name string

	// CountryCode — ISO-3166 alpha-2 ("BR", "GB"), best-effort.
	CountryCode string

	// CurrentSeason — provider-native season label ("2026", "2025/26").
	CurrentSeason string

	// SourceID — the adapter that owns this descriptor.
	SourceID string
}

// FixtureFetchRequest is what the orchestrator hands to an adapter
// when it wants fixtures for a specific competition. CompetitionID
// is the HUB's canonical UUID — the adapter resolves to its own
// provider-native id via its internal mapping (typically the
// CompetitionRegistry).
type FixtureFetchRequest struct {
	CompetitionID uuid.UUID
	// Season — provider-native label. Adapter passes through.
	// Empty means "current season" per the provider's default.
	Season string
	// From/To — optional time window. Zero values mean "no bound".
	// Adapters MAY clamp to provider-supported windows + log.
	From time.Time
	To   time.Time
}

// StandingsFetchRequest — same shape as FixtureFetchRequest for now;
// kept as a separate type so future divergence (e.g. group filter)
// doesn't require breaking changes.
type StandingsFetchRequest struct {
	CompetitionID uuid.UUID
	Season        string
}

// HistoricalFetchRequest is the shared shape for historical/backfill reads.
// It intentionally lives in ports because adapters receive it, while the
// validation logic lives in the sync domain package.
type HistoricalFetchRequest struct {
	CompetitionID uuid.UUID
	Season        string
	From          time.Time
	To            time.Time
}

// HistoricalOddsFetchRequest is separate because odds providers often need
// provider-specific market/region filters. Those values stay generic here and
// provider mapping remains inside the adapter.
type HistoricalOddsFetchRequest struct {
	CompetitionID uuid.UUID
	Season        string
	From          time.Time
	To            time.Time
	Markets       []string
	Regions       []string
}

// OddsFetchRequest describes a realtime/current odds fetch. MatchID is optional
// because some providers expose competition-level odds first and fixture-level
// filtering later.
type OddsFetchRequest struct {
	CompetitionID uuid.UUID
	MatchID       uuid.UUID
	Markets       []string
	Regions       []string
}

// Optional adapter interfaces. SourceAdapter remains backward-compatible for
// existing providers. New providers implement only the extra interfaces they
// truly support; capabilities must mirror actual implementation, not provider
// marketing claims.
type HistoricalFixturesAdapter interface {
	FetchHistoricalFixtures(ctx context.Context, req HistoricalFetchRequest) ([]*event.RawSportsEvent, error)
}

type HistoricalResultsAdapter interface {
	FetchHistoricalResults(ctx context.Context, req HistoricalFetchRequest) ([]*event.RawSportsEvent, error)
}

type HistoricalStandingsAdapter interface {
	FetchHistoricalStandings(ctx context.Context, req HistoricalFetchRequest) ([]*event.RawSportsEvent, error)
}

type OddsAdapter interface {
	FetchOdds(ctx context.Context, req OddsFetchRequest) ([]*event.RawSportsEvent, error)
}

type HistoricalOddsAdapter interface {
	FetchHistoricalOdds(ctx context.Context, req HistoricalOddsFetchRequest) ([]*event.RawSportsEvent, error)
}

type PlayersAdapter interface {
	FetchPlayers(ctx context.Context, req FixtureFetchRequest) ([]*event.RawSportsEvent, error)
}

type HistoricalPlayersAdapter interface {
	FetchHistoricalPlayers(ctx context.Context, req HistoricalFetchRequest) ([]*event.RawSportsEvent, error)
}

type LineupsAdapter interface {
	FetchLineups(ctx context.Context, req FixtureFetchRequest) ([]*event.RawSportsEvent, error)
}

type HistoricalLineupsAdapter interface {
	FetchHistoricalLineups(ctx context.Context, req HistoricalFetchRequest) ([]*event.RawSportsEvent, error)
}

type InjuriesAdapter interface {
	FetchInjuries(ctx context.Context, req FixtureFetchRequest) ([]*event.RawSportsEvent, error)
}

type HistoricalInjuriesAdapter interface {
	FetchHistoricalInjuries(ctx context.Context, req HistoricalFetchRequest) ([]*event.RawSportsEvent, error)
}

// HealthSnapshot — the operational state the HTTP /providers/status
// endpoint exposes. All fields are best-effort; an adapter that's
// never been called returns the zero value.
//
// Sprint 2.1 enrichment: Capabilities, RatePolicy, PollPolicies
// surface the static profile registered at boot — adminis tooling
// renders both the live counters AND the configured envelope from a
// single response.
type HealthSnapshot struct {
	SourceID            string
	Reachable           bool
	LastSuccessfulSync  time.Time
	LastFailure         time.Time
	LastError           string // single-line summary; never includes secrets
	AverageLatencyMs    int64
	RequestsTotal       int64
	RequestsFailedTotal int64

	// Sprint 2.1 — static profile registered at boot via the
	// ProviderStatusRecorder. Zero values are valid (unregistered).
	Capabilities source.ProviderCapability
	RatePolicy   syncdom.RateLimitPolicy
	PollPolicies []syncdom.PollPolicy

	// Sprint 3 — scheduler/runner lifecycle counters. Mutated by
	// the dispatcher (queued/dropped) and the runner
	// (started→running, completed, failed, rate-limit-blocked).
	QueuedJobs             int64
	RunningJobs            int64
	CompletedJobs          int64
	FailedJobs             int64
	QueueDroppedTotal      int64
	RateLimitBlockedTotal  int64
	LastExecution          time.Time
	NextScheduledExecution time.Time
}
