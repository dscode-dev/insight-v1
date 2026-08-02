// Planner tests — Sprint 3.
//
// Architectural rules verified here:
//   - "Disabled competitions generate zero jobs."
//   - "Do not generate jobs that the provider cannot execute."
//   - "Adapters never know polling intervals." (Planner consumes the
//     PollPolicy; the adapter test stub deliberately panics if its
//     fetch methods are called — they must not be.)
package application_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/application/scheduler"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// ---------------------------------------------------------------------------
// Fakes
// ---------------------------------------------------------------------------

type fakeAdapter struct {
	identity ports.AdapterIdentity
}

func (a *fakeAdapter) Identity() ports.AdapterIdentity { return a.identity }
func (a *fakeAdapter) FetchCompetitions(context.Context) ([]ports.CompetitionDescriptor, error) {
	panic("planner must not invoke adapter.FetchCompetitions")
}
func (a *fakeAdapter) FetchFixtures(context.Context, ports.FixtureFetchRequest) ([]*event.RawSportsEvent, error) {
	panic("planner must not invoke adapter.FetchFixtures")
}
func (a *fakeAdapter) FetchStandings(context.Context, ports.StandingsFetchRequest) ([]*event.RawSportsEvent, error) {
	panic("planner must not invoke adapter.FetchStandings")
}
func (a *fakeAdapter) Health() ports.HealthSnapshot { return ports.HealthSnapshot{} }

type fakeCompetitionRegistry struct {
	comps []ports.Competition
}

func (r *fakeCompetitionRegistry) IsKnown(context.Context, uuid.UUID) (bool, error) {
	return true, nil
}
func (r *fakeCompetitionRegistry) Register(context.Context, ports.Competition) error { return nil }
func (r *fakeCompetitionRegistry) Lookup(context.Context, uuid.UUID) (ports.Competition, error) {
	return ports.Competition{}, nil
}
func (r *fakeCompetitionRegistry) LookupByExternalID(context.Context, string, string) (ports.Competition, error) {
	return ports.Competition{}, nil
}
func (r *fakeCompetitionRegistry) LinkExternalID(context.Context, uuid.UUID, string, string) error {
	return nil
}
func (r *fakeCompetitionRegistry) GetExternalIDForSource(context.Context, uuid.UUID, string) (string, error) {
	return "", nil
}
func (r *fakeCompetitionRegistry) SetEnabled(context.Context, uuid.UUID, bool) error { return nil }
func (r *fakeCompetitionRegistry) List(context.Context) ([]ports.Competition, error) {
	return r.comps, nil
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func capsAll() source.ProviderCapability {
	return source.ProviderCapability{
		SupportsFixtures: true, SupportsResults: true, SupportsStandings: true,
		SupportsOdds: false, SupportsLineups: false, SupportsNews: false,
	}
}

func newAdapter(id string, caps source.ProviderCapability) ports.SourceAdapter {
	return &fakeAdapter{identity: ports.AdapterIdentity{
		SourceID:     id,
		SourceName:   id,
		SourceType:   source.TypeCommercialAPI,
		Capabilities: caps,
	}}
}

func mustPolicy(t *testing.T, sourceID string, st syncdom.SyncType, every time.Duration) syncdom.PollPolicy {
	t.Helper()
	p, err := syncdom.NewPollPolicy(sourceID, st, every, 0, true)
	if err != nil {
		t.Fatalf("policy: %v", err)
	}
	return p
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

func TestPlannerSkipsDisabledCompetitions(t *testing.T) {
	c := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}

	disabled := uuid.New()
	enabled := uuid.New()
	registry := &fakeCompetitionRegistry{
		comps: []ports.Competition{
			{ID: disabled, Slug: "off", Name: "Off", Enabled: false},
			{ID: enabled, Slug: "on", Name: "On", Enabled: true},
		},
	}

	adapters := map[string]ports.SourceAdapter{
		"api_football": newAdapter("api_football", capsAll()),
	}
	policies := map[string][]syncdom.PollPolicy{
		"api_football": {mustPolicy(t, "api_football", syncdom.TypeFixtures, time.Minute)},
	}

	planner := scheduler.NewPlanner(adapters, registry, policies, c)
	jobs, err := planner.Plan(context.Background())
	if err != nil {
		t.Fatalf("plan err: %v", err)
	}
	if len(jobs) != 1 {
		t.Fatalf("expected 1 job (enabled only), got %d", len(jobs))
	}
	if jobs[0].CompetitionID != enabled {
		t.Errorf("disabled competition leaked into plan")
	}
}

func TestPlannerSkipsUnsupportedSyncTypes(t *testing.T) {
	c := &stepClock{now: time.Now()}
	comp := uuid.New()
	registry := &fakeCompetitionRegistry{
		comps: []ports.Competition{{ID: comp, Slug: "x", Name: "X", Enabled: true}},
	}

	// Provider supports fixtures but NOT odds.
	caps := source.ProviderCapability{SupportsFixtures: true}
	adapters := map[string]ports.SourceAdapter{
		"p": newAdapter("p", caps),
	}
	// Two policies — one supported, one not.
	policies := map[string][]syncdom.PollPolicy{
		"p": {
			mustPolicy(t, "p", syncdom.TypeFixtures, time.Minute),
			mustPolicy(t, "p", syncdom.TypeOdds, time.Minute),
		},
	}

	planner := scheduler.NewPlanner(adapters, registry, policies, c)
	jobs, _ := planner.Plan(context.Background())
	if len(jobs) != 1 {
		t.Fatalf("expected 1 job (fixtures only), got %d", len(jobs))
	}
	if jobs[0].SyncType != syncdom.TypeFixtures {
		t.Errorf("planned wrong sync_type: %s", jobs[0].SyncType)
	}
}

func TestPlannerRespectsPollInterval(t *testing.T) {
	c := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	comp := uuid.New()
	registry := &fakeCompetitionRegistry{
		comps: []ports.Competition{{ID: comp, Slug: "x", Name: "X", Enabled: true}},
	}
	adapters := map[string]ports.SourceAdapter{
		"p": newAdapter("p", capsAll()),
	}
	policies := map[string][]syncdom.PollPolicy{
		"p": {mustPolicy(t, "p", syncdom.TypeFixtures, 30*time.Minute)},
	}
	planner := scheduler.NewPlanner(adapters, registry, policies, c)

	first, _ := planner.Plan(context.Background())
	if len(first) != 1 {
		t.Fatalf("first plan = %d, want 1", len(first))
	}

	// Immediately re-plan — must NOT emit again because the interval
	// hasn't elapsed.
	second, _ := planner.Plan(context.Background())
	if len(second) != 0 {
		t.Errorf("second plan must be empty inside interval, got %d jobs", len(second))
	}

	// Advance past the interval.
	c.Advance(31 * time.Minute)
	third, _ := planner.Plan(context.Background())
	if len(third) != 1 {
		t.Errorf("third plan after interval = %d, want 1", len(third))
	}
}

func TestPlannerSkipsDisabledPolicies(t *testing.T) {
	c := &stepClock{now: time.Now()}
	comp := uuid.New()
	registry := &fakeCompetitionRegistry{
		comps: []ports.Competition{{ID: comp, Slug: "x", Name: "X", Enabled: true}},
	}
	adapters := map[string]ports.SourceAdapter{
		"p": newAdapter("p", capsAll()),
	}
	disabledPolicy, _ := syncdom.NewPollPolicy(
		"p", syncdom.TypeFixtures, time.Minute, 0, false, // Enabled=false
	)
	policies := map[string][]syncdom.PollPolicy{
		"p": {disabledPolicy},
	}
	planner := scheduler.NewPlanner(adapters, registry, policies, c)
	jobs, _ := planner.Plan(context.Background())
	if len(jobs) != 0 {
		t.Errorf("disabled policy must produce zero jobs, got %d", len(jobs))
	}
}
