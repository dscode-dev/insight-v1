// Application layer — router, context builder, draft generator, and
// the full publishing pipeline over in-memory adapters.
package application_test

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/adapters/inmemory"
	"github.com/konoha-labs/insight-nexus/internal/application/agentstate"
	"github.com/konoha-labs/insight-nexus/internal/application/clustering"
	"github.com/konoha-labs/insight-nexus/internal/application/clusterlifecycle"
	"github.com/konoha-labs/insight-nexus/internal/application/contextbuilder"
	"github.com/konoha-labs/insight-nexus/internal/application/draftgen"
	"github.com/konoha-labs/insight-nexus/internal/application/evolution"
	"github.com/konoha-labs/insight-nexus/internal/application/matchsweep"
	"github.com/konoha-labs/insight-nexus/internal/application/pipeline"
	"github.com/konoha-labs/insight-nexus/internal/application/publication"
	"github.com/konoha-labs/insight-nexus/internal/application/router"
	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
)

// stubMetrics counts everything, race-safe.
type stubMetrics struct {
	mu                     sync.Mutex
	consumed, hits, misses int
	drafts, candidates     map[string]int
}

func newStubMetrics() *stubMetrics {
	return &stubMetrics{drafts: map[string]int{}, candidates: map[string]int{}}
}
func (m *stubMetrics) TrendConsumed() { m.mu.Lock(); m.consumed++; m.mu.Unlock() }
func (m *stubMetrics) DraftGenerated(a string) {
	m.mu.Lock()
	m.drafts[a]++
	m.mu.Unlock()
}
func (m *stubMetrics) PublicationCandidate(a string) {
	m.mu.Lock()
	m.candidates[a]++
	m.mu.Unlock()
}
func (m *stubMetrics) MemoryHit()  { m.mu.Lock(); m.hits++; m.mu.Unlock() }
func (m *stubMetrics) MemoryMiss() { m.mu.Lock(); m.misses++; m.mu.Unlock() }

func officialAgents(t *testing.T, repo *inmemory.AgentRepo) map[string]agent.Agent {
	t.Helper()
	specs := map[string][]string{
		"ninja":    {"market_shift", "market_conviction", "market_acceleration", "ninja"},
		"pulse":    {"momentum_shift", "pressure_building", "dominance_pattern", "imminent_breakthrough", "pulse"},
		"oracle":   {"historical_deviation", "historical_pattern", "historical_similarity", "oracle"},
		"sentinel": {"impact_assessment", "risk_increase", "risk_escalation", "game_state_change", "sentinel"},
		"echo":     {"narrative_divergence", "narrative_conflict", "sentiment_shift", "community_signal", "echo"},
	}
	out := map[string]agent.Agent{}
	for name, types := range specs {
		a := agent.Agent{
			ID: uuid.New(), Name: name, Specialty: name, Active: true,
			TrendTypes: types, CreatedAt: time.Now(), UpdatedAt: time.Now(),
		}
		if err := repo.Create(context.Background(), a); err != nil {
			t.Fatalf("seed %s: %v", name, err)
		}
		out[name] = a
	}
	return out
}

func trendEvent(trendType, category string) trend.Event {
	return trend.Event{
		TrendID:         uuid.NewString(),
		SchemaVersion:   "v3",
		TrendType:       trendType,
		Category:        category,
		Confidence:      0.8,
		Severity:        "high",
		MatchID:         uuid.NewString(),
		Strength:        0.7,
		Title:           "Some structured title",
		Summary:         "Some structured summary.",
		Meaning:         "market_confidence_increasing",
		MeaningCategory: "market_behavior",
		LifecycleState:  "strengthening",
		PublicationTier: "publish",
		CreatedAt:       "2026-06-01T10:00:00Z",
		Timeline:        map[string]any{"previous_states": []any{"active"}},
		Pattern:         map[string]any{"occurrences": float64(3), "historical_success_rate": 0.72},
		ChartData:       map[string]any{"kind": "implied_probability"},
	}
}

func newPipeline(t *testing.T) (*pipeline.Pipeline, *inmemory.AgentRepo, *inmemory.MemoryRepo,
	*inmemory.DraftRepo, *inmemory.PublicationRepo, *inmemory.Queue, *stubMetrics) {
	t.Helper()
	agents := inmemory.NewAgentRepo()
	memories := inmemory.NewMemoryRepo()
	drafts := inmemory.NewDraftRepo()
	pubs := inmemory.NewPublicationRepo()
	queue := inmemory.NewQueue()
	metrics := newStubMetrics()
	fixed := func() time.Time { return time.Date(2026, 6, 1, 10, 0, 0, 0, time.UTC) }
	clusterRepo := inmemory.NewClusterRepo()
	stateRepo := inmemory.NewAgentStateRepo()
	lifecycle := clusterlifecycle.New(clusterRepo, clusterlifecycle.Config{}, zerolog.Nop(), fixed)
	p := pipeline.New(pipeline.Deps{
		Router:     router.New(agents, zerolog.Nop()),
		Clustering: clustering.New(clusterRepo, fixed, 90*time.Minute),
		Lifecycle:  lifecycle,
		Sweep: matchsweep.New(stateRepo, lifecycle,
			matchsweep.Config{}, zerolog.Nop(), fixed),
		Decisions:    publication.New(publication.Config{}),
		States:       agentstate.New(stateRepo, fixed),
		Evolution:    evolution.New(inmemory.NewEvolutionRepo(), fixed),
		Builder:      contextbuilder.New(memories, metrics),
		Generator:    draftgen.New(fixed),
		Drafts:       drafts,
		Memories:     memories,
		Publications: pubs,
		DecisionRepo: inmemory.NewDecisionRepo(),
		Queue:        queue,
		Metrics:      metrics,
		Logger:       zerolog.Nop(),
		Now:          fixed,
	})
	return p, agents, memories, drafts, pubs, queue, metrics
}

// --- router -------------------------------------------------------------------

func TestRouterRoutesByAgentConfiguration(t *testing.T) {
	p, agents, _, _, _, _, _ := newPipeline(t)
	_ = p
	officialAgents(t, agents)
	r := router.New(agents, zerolog.Nop())

	cases := map[string][]string{
		"market_conviction":     {"ninja"},
		"imminent_breakthrough": {"pulse"},
		"historical_deviation":  {"oracle"},
		"risk_escalation":       {"sentinel"},
		"narrative_divergence":  {"echo"},
	}
	for trendType, want := range cases {
		matched, err := r.Route(context.Background(), trendEvent(trendType, "x"))
		if err != nil {
			t.Fatal(err)
		}
		names := make([]string, 0, len(matched))
		for _, a := range matched {
			names = append(names, a.Name)
		}
		if len(names) != len(want) || names[0] != want[0] {
			t.Errorf("%s routed to %v, want %v", trendType, names, want)
		}
	}
}

func TestRouterMultipleAgentsAndDisabled(t *testing.T) {
	agents := inmemory.NewAgentRepo()
	seeded := officialAgents(t, agents)
	// market_shift is consumed by ninja; echo ALSO consumes it once
	// configured (multiple agents may receive the same trend).
	echo := seeded["echo"]
	echo.TrendTypes = append(echo.TrendTypes, "market_shift")
	if err := agents.Update(context.Background(), echo); err != nil {
		t.Fatal(err)
	}
	r := router.New(agents, zerolog.Nop())
	matched, _ := r.Route(context.Background(), trendEvent("market_shift", "ninja"))
	if len(matched) != 2 {
		t.Fatalf("expected ninja + echo, got %d", len(matched))
	}
	// Disable ninja → only echo.
	_ = agents.SetActive(context.Background(), seeded["ninja"].ID, false)
	matched, _ = r.Route(context.Background(), trendEvent("market_shift", "ninja"))
	if len(matched) != 1 || matched[0].Name != "echo" {
		t.Errorf("disabled agent must not route: %v", matched)
	}
}

// --- draft generator ------------------------------------------------------------

func TestDraftGeneratorStructuredAndDeterministic(t *testing.T) {
	a := agent.Agent{ID: uuid.New(), Name: "ninja", Specialty: "Market Intelligence",
		Active: true, TrendTypes: []string{"ninja"}}
	ev := trendEvent("market_conviction", "fusion")
	gen := draftgen.New(func() time.Time { return time.Date(2026, 6, 1, 10, 0, 0, 0, time.UTC) })
	dc := contextbuilder.DraftContext{
		Agent: a, Trend: ev, StreamPriority: true,
		Memories: []memory.Memory{{
			ID: uuid.New(), AgentID: a.ID, Summary: "market_shift: market_sentiment_shifting (active)",
		}},
		MemoryHit:   true,
		ClusterType: "MARKET_CONFIDENCE",
		Action:      "HIGH_PRIORITY_DRAFT",
		Priority:    "HIGH",
		AgentState:  "TRACKING",
		DraftType:   "FOLLOW_UP",
		Sequence:    2,
	}
	d := gen.Generate(dc)
	if d.Title != ev.Title || d.Summary != ev.Summary {
		t.Error("title/summary must be Atlas's structured text, never generated")
	}
	joined := strings.Join(d.Highlights, "|")
	for _, want := range []string{
		"meaning: market_confidence_increasing",
		"lifecycle: strengthening (was: active)",
		"pattern: seen 3 time(s) before, 72% confirmed",
		"continuity: market_shift",
	} {
		if !strings.Contains(joined, want) {
			t.Errorf("highlights missing %q: %v", want, d.Highlights)
		}
	}
	if len(d.Charts) != 1 {
		t.Errorf("chart_data must propagate: %v", d.Charts)
	}
	if d.Metadata["priority"] != "high" || d.Metadata["publication_tier"] != "publish" {
		t.Errorf("metadata incomplete: %v", d.Metadata)
	}
	if d.Metadata["visibility"] != "competition" || d.Metadata["draft_type"] != "follow_up" {
		t.Errorf("feed-readiness metadata wrong: %v", d.Metadata)
	}
	// Determinism: same context (modulo fresh draft id) → same content.
	d2 := gen.Generate(dc)
	if d2.Title != d.Title || strings.Join(d2.Highlights, "|") != joined {
		t.Error("draft content must be deterministic")
	}
}

// --- pipeline e2e ----------------------------------------------------------------

func TestPipelineEndToEnd(t *testing.T) {
	p, agents, _, drafts, pubs, queue, metrics := newPipeline(t)
	seeded := officialAgents(t, agents)

	env := trend.Envelope{SchemaVersion: "v3", Priority: true,
		Trend: trendEvent("market_conviction", "fusion")}
	result, err := p.HandleTrend(context.Background(), env)
	if err != nil {
		t.Fatal(err)
	}
	if result.RoutedAgents != 1 || len(result.Drafts) != 1 {
		t.Fatalf("expected one ninja draft: %+v", result)
	}

	// Draft persisted, memory written, candidate recorded, queue fed.
	if len(drafts.All()) != 1 {
		t.Error("draft not persisted")
	}
	cands := pubs.All()
	// Sprint 3: queue priority is DECISION-driven. A "publish"-tier
	// trend resolves to DRAFT — not a priority enqueue, even though the
	// stream entry carried Atlas's priority flag.
	if len(cands) != 1 || cands[0].Queue != "insight:queue:nexus:ninja" || cands[0].Priority {
		t.Errorf("candidate wrong: %+v", cands)
	}
	depth, _ := queue.Depth(context.Background(), "insight:queue:nexus:ninja")
	if depth != 1 {
		t.Errorf("queue depth: %d", depth)
	}
	if metrics.consumed != 1 || metrics.drafts["ninja"] != 1 || metrics.candidates["ninja"] != 1 {
		t.Errorf("metrics: %+v", metrics)
	}
	if metrics.misses != 1 {
		t.Errorf("first trend must be a memory miss: %+v", metrics)
	}

	// Second trend for the SAME match: ninja now has a memory → hit,
	// and the new draft references continuity.
	env2 := env
	env2.Trend.TrendID = uuid.NewString()
	if _, err := p.HandleTrend(context.Background(), env2); err != nil {
		t.Fatal(err)
	}
	if metrics.hits != 1 {
		t.Errorf("second trend must be a memory hit: %+v", metrics)
	}
	all := drafts.All()
	last := all[len(all)-1]
	found := false
	for _, h := range last.Highlights {
		if strings.HasPrefix(h, "continuity: market_conviction") {
			found = true
		}
	}
	if !found {
		t.Errorf("second draft must reference the prior memory: %v", last.Highlights)
	}
	_ = seeded
}

func TestPipelineUnroutedTrendProducesNothing(t *testing.T) {
	p, agents, _, drafts, _, _, metrics := newPipeline(t)
	officialAgents(t, agents)
	env := trend.Envelope{SchemaVersion: "v3",
		Trend: trendEvent("tempo_change", "unmatched_category")}
	result, err := p.HandleTrend(context.Background(), env)
	if err != nil {
		t.Fatal(err)
	}
	if result.RoutedAgents != 0 || len(drafts.All()) != 0 {
		t.Errorf("unrouted trend must produce nothing: %+v", result)
	}
	if metrics.consumed != 1 {
		t.Error("consumption still counted")
	}
}

// --- memory window -----------------------------------------------------------------

func TestContextBuilderReturnsLastTenMemories(t *testing.T) {
	memories := inmemory.NewMemoryRepo()
	metrics := newStubMetrics()
	b := contextbuilder.New(memories, metrics)
	a := agent.Agent{ID: uuid.New(), Name: "ninja", Specialty: "x",
		TrendTypes: []string{"ninja"}, Active: true}
	matchID := uuid.NewString()
	for i := 0; i < 15; i++ {
		_ = memories.Save(context.Background(), memory.Memory{
			ID: uuid.New(), AgentID: a.ID, MatchID: matchID,
			TrendID: uuid.NewString(), Summary: "obs",
			CreatedAt: time.Date(2026, 6, 1, 10, i, 0, 0, time.UTC),
		})
	}
	dc, err := b.Build(context.Background(), a, trend.Event{
		TrendID: "t", TrendType: "market_shift", MatchID: matchID,
	}, false, "MARKET_CONFIDENCE")
	if err != nil {
		t.Fatal(err)
	}
	if len(dc.Memories) != contextbuilder.MemoryWindow {
		t.Errorf("memory window: got %d want %d", len(dc.Memories), contextbuilder.MemoryWindow)
	}
	// Newest first.
	if !dc.Memories[0].CreatedAt.After(dc.Memories[1].CreatedAt) {
		t.Error("memories must be newest-first")
	}
}
