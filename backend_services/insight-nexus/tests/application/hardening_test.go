// Sprint 3.5 — cluster lifecycle, match end sweep, narrative health,
// and the Priority rename backward-compat contract.
package application_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/adapters/inmemory"
	"github.com/konoha-labs/insight-nexus/internal/application/clustering"
	"github.com/konoha-labs/insight-nexus/internal/application/clusterlifecycle"
	"github.com/konoha-labs/insight-nexus/internal/application/contextbuilder"
	"github.com/konoha-labs/insight-nexus/internal/application/draftgen"
	"github.com/konoha-labs/insight-nexus/internal/application/matchsweep"
	"github.com/konoha-labs/insight-nexus/internal/application/narrativehealth"
	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	domainevolution "github.com/konoha-labs/insight-nexus/internal/domain/evolution"
	"github.com/konoha-labs/insight-nexus/internal/domain/state"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
)

func lifecycleEngine(repo *inmemory.ClusterRepo) *clusterlifecycle.Engine {
	return clusterlifecycle.New(repo, clusterlifecycle.Config{}, zerolog.Nop(), fixedNow)
}

func openCluster(t *testing.T, repo *inmemory.ClusterRepo, matchID string,
	confidence float64) cluster.TrendCluster {
	t.Helper()
	eng := clustering.New(repo, fixedNow, 90*time.Minute)
	ev := trendEvent("pressure_building", "pulse")
	ev.MatchID = matchID
	ev.Confidence = confidence
	c, _, err := eng.Assign(context.Background(), ev)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

// --- Part 1: cluster lifecycle -------------------------------------------------

func TestClusterCompletesOnConfirmedLifecycle(t *testing.T) {
	repo := inmemory.NewClusterRepo()
	c := openCluster(t, repo, uuid.NewString(), 0.8)
	ev := trendEvent("pressure_building", "pulse")
	ev.MatchID = c.MatchID
	ev.LifecycleState = "confirmed"

	closed, didClose, err := lifecycleEngine(repo).EvaluateTrend(
		context.Background(), c, ev)
	if err != nil || !didClose {
		t.Fatalf("confirmed trend must complete the cluster: %v", err)
	}
	if closed.State != cluster.ClusterCompleted ||
		closed.CloseReason != cluster.ReasonLifecycleConfirmed {
		t.Errorf("closure wrong: %s/%s", closed.State, closed.CloseReason)
	}
	if closed.ClosedAt == nil {
		t.Error("closed_at must be set")
	}
}

func TestClusterFailsOnlyWhenConfidenceCollapsed(t *testing.T) {
	repo := inmemory.NewClusterRepo()
	eng := lifecycleEngine(repo)

	// Strong story (confidence 0.8 ≥ floor 0.5): one failed trend does
	// NOT close it.
	strong := openCluster(t, repo, uuid.NewString(), 0.8)
	ev := trendEvent("pressure_building", "pulse")
	ev.MatchID = strong.MatchID
	ev.LifecycleState = "failed"
	_, didClose, _ := eng.EvaluateTrend(context.Background(), strong, ev)
	if didClose {
		t.Error("strong story must survive one failed trend")
	}

	// Collapsed story (confidence 0.3 < floor): FAILED.
	weak := openCluster(t, repo, uuid.NewString(), 0.3)
	ev.MatchID = weak.MatchID
	closed, didClose, _ := eng.EvaluateTrend(context.Background(), weak, ev)
	if !didClose || closed.State != cluster.ClusterFailed {
		t.Errorf("collapsed story must fail: %v %s", didClose, closed.State)
	}
}

func TestClusterExpiresOnInactivityAndReopensFresh(t *testing.T) {
	repo := inmemory.NewClusterRepo()
	matchID := uuid.NewString()

	// Open at T0 via a clock we can advance past the 90-minute window.
	current := fixedNow()
	clock := func() time.Time { return current }
	eng := clustering.New(repo, clock, 90*time.Minute)

	ev := trendEvent("pressure_building", "pulse")
	ev.MatchID = matchID
	first, _, err := eng.Assign(context.Background(), ev)
	if err != nil {
		t.Fatal(err)
	}

	// 91 minutes of silence, then a new trend for the same story.
	current = current.Add(91 * time.Minute)
	ev2 := trendEvent("dominance_pattern", "pulse")
	ev2.MatchID = matchID
	second, created, err := eng.Assign(context.Background(), ev2)
	if err != nil {
		t.Fatal(err)
	}
	if !created || second.ID == first.ID {
		t.Fatal("stale story must expire and a FRESH cluster must open")
	}
	// The old cluster is closed as EXPIRED — never reused.
	all, _ := repo.List(context.Background(), 10)
	var old cluster.TrendCluster
	for _, c := range all {
		if c.ID == first.ID {
			old = c
		}
	}
	if old.State != cluster.ClusterExpired || old.CloseReason != cluster.ReasonInactivity {
		t.Errorf("old cluster: %s/%s", old.State, old.CloseReason)
	}
}

func TestClosedClusterNeverReused(t *testing.T) {
	repo := inmemory.NewClusterRepo()
	c := openCluster(t, repo, uuid.NewString(), 0.8)
	if _, _, err := lifecycleEngine(repo).CompleteOnRetrospective(
		context.Background(), c); err != nil {
		t.Fatal(err)
	}
	// Next trend for the same story → brand-new cluster.
	eng := clustering.New(repo, fixedNow, 90*time.Minute)
	ev := trendEvent("momentum_shift", "pulse")
	ev.MatchID = c.MatchID
	fresh, created, err := eng.Assign(context.Background(), ev)
	if err != nil || !created || fresh.ID == c.ID {
		t.Errorf("closed cluster must never be reused: created=%v same=%v err=%v",
			created, fresh.ID == c.ID, err)
	}
}

// --- Part 2: match end sweep ------------------------------------------------------

func TestMatchSweepClosesEverything(t *testing.T) {
	clusterRepo := inmemory.NewClusterRepo()
	stateRepo := inmemory.NewAgentStateRepo()
	matchID := uuid.NewString()
	c := openCluster(t, clusterRepo, matchID, 0.8)

	// Two engaged agent states on the match.
	for _, st := range []state.State{state.Tracking, state.Alerting} {
		s := state.AgentState{
			ID: uuid.New(), AgentID: uuid.New(), MatchID: matchID,
			ClusterID: c.ID, ClusterType: string(c.ClusterType),
			Current: state.Idle, CreatedAt: fixedNow(), UpdatedAt: fixedNow(),
		}
		s.Apply(st, "test", fixedNow())
		if err := stateRepo.Save(context.Background(), s); err != nil {
			t.Fatal(err)
		}
	}

	sweep := matchsweep.New(stateRepo, lifecycleEngine(clusterRepo),
		matchsweep.Config{}, zerolog.Nop(), fixedNow)

	// A fulltime game_state_change triggers the sweep.
	ev := trendEvent("game_state_change", "sentinel")
	ev.MatchID = matchID
	ev.Metrics = map[string]any{"from": "late", "to": "fulltime"}
	result, err := sweep.MaybeSweep(context.Background(), ev)
	if err != nil || !result.Swept {
		t.Fatalf("fulltime must sweep: %+v err=%v", result, err)
	}
	if result.Retrospectives != 2 || result.ClustersClosed != 1 {
		t.Errorf("sweep result: %+v", result)
	}

	// No active states remain after match completion.
	active, _ := stateRepo.ListActiveByMatch(context.Background(), matchID)
	if len(active) != 0 {
		t.Errorf("active states must be empty after sweep: %d", len(active))
	}
	open, _ := clusterRepo.ListActiveByMatch(context.Background(), matchID)
	if len(open) != 0 {
		t.Errorf("open clusters must be empty after sweep: %d", len(open))
	}
}

func TestMatchSweepIgnoresNonTerminalMarkers(t *testing.T) {
	sweep := matchsweep.New(inmemory.NewAgentStateRepo(),
		lifecycleEngine(inmemory.NewClusterRepo()),
		matchsweep.Config{}, zerolog.Nop(), fixedNow)
	ev := trendEvent("game_state_change", "sentinel")
	ev.Metrics = map[string]any{"from": "first_half", "to": "second_half"}
	result, err := sweep.MaybeSweep(context.Background(), ev)
	if err != nil || result.Swept {
		t.Errorf("half-time transition must not sweep: %+v", result)
	}
}

// --- Part 4: Priority rename backward compatibility -------------------------------

func TestPriorityRenameKeepsWireContract(t *testing.T) {
	a := agent.Agent{ID: uuid.New(), Name: "ninja", Specialty: "x",
		Active: true, TrendTypes: []string{"ninja"}}
	gen := draftgen.New(fixedNow)

	// Decision band drives the metadata key — exactly as before the
	// rename (key "priority", lowercased band).
	dc := contextbuilder.DraftContext{
		Agent: a, Trend: trendEvent("market_shift", "ninja"),
		Priority: "CRITICAL", DraftType: "FOLLOW_UP",
		ClusterType: "MARKET_CONFIDENCE", Sequence: 2,
	}
	d := gen.Generate(dc)
	if d.Metadata["priority"] != "critical" {
		t.Errorf("wire key 'priority' must carry the band: %v", d.Metadata["priority"])
	}

	// Fallback: no decision band → the stream flag still maps high/medium.
	dc2 := contextbuilder.DraftContext{
		Agent: a, Trend: trendEvent("market_shift", "ninja"), StreamPriority: true,
	}
	if got := gen.Generate(dc2).Metadata["priority"]; got != "high" {
		t.Errorf("stream-priority fallback broken: %v", got)
	}
}

// --- Part 5: narrative health -------------------------------------------------------

func TestNarrativeHealthScoresStories(t *testing.T) {
	clusterRepo := inmemory.NewClusterRepo()
	evolutionRepo := inmemory.NewEvolutionRepo()
	health := narrativehealth.New(clusterRepo, evolutionRepo,
		narrativehealth.Weights{}, fixedNow)
	ctx := context.Background()

	// Healthy story: confident, diverse, confirmed, continuous.
	healthy := cluster.TrendCluster{
		ID: uuid.New(), MatchID: uuid.NewString(),
		ClusterType: cluster.AttackingPressure,
		TrendIDs:    []string{"a", "b", "c"},
		TrendTypes:  []string{"pressure_building", "dominance_pattern", "momentum_shift"},
		Confidence:  0.9, State: cluster.ClusterCompleted,
		OpenedAt:  fixedNow().Add(-30 * time.Minute),
		CreatedAt: fixedNow().Add(-30 * time.Minute),
		UpdatedAt: fixedNow(),
	}
	_ = clusterRepo.Save(ctx, healthy)
	agentID := uuid.New()
	for i, dt := range []domainevolution.DraftType{
		domainevolution.InitialObservation,
		domainevolution.FollowUp,
		domainevolution.Confirmation,
	} {
		_ = evolutionRepo.Record(ctx, domainevolution.Record{
			ID: uuid.New(), AgentID: agentID, ClusterID: healthy.ID,
			DraftID: uuid.New(), MatchID: healthy.MatchID,
			DraftType: dt, Sequence: i + 1, CreatedAt: fixedNow(),
		})
	}

	// Sick story: weak, narrow, failed, no development.
	sick := cluster.TrendCluster{
		ID: uuid.New(), MatchID: uuid.NewString(),
		ClusterType: cluster.MarketConfidence,
		TrendIDs:    []string{"x"}, TrendTypes: []string{"market_shift"},
		Confidence: 0.3, State: cluster.ClusterFailed,
		OpenedAt: fixedNow(), CreatedAt: fixedNow(), UpdatedAt: fixedNow(),
	}
	_ = clusterRepo.Save(ctx, sick)

	h1, err := health.Compute(ctx, healthy)
	if err != nil {
		t.Fatal(err)
	}
	h2, err := health.Compute(ctx, sick)
	if err != nil {
		t.Fatal(err)
	}
	if h1.HealthScore <= h2.HealthScore {
		t.Errorf("healthy %v must outscore sick %v", h1.HealthScore, h2.HealthScore)
	}
	if h1.HealthScore < 0.8 {
		t.Errorf("fully corroborated confirmed story should score high: %v", h1.HealthScore)
	}
	if h2.HealthScore > 0.2 {
		t.Errorf("failed isolated story should score low: %v", h2.HealthScore)
	}
	if h1.TrendCount != 3 || h1.DraftCount != 3 || h1.Lifespan != 30*time.Minute {
		t.Errorf("health facts wrong: %+v", h1)
	}
	// Determinism.
	again, _ := health.Compute(ctx, healthy)
	if again.HealthScore != h1.HealthScore {
		t.Error("health must be deterministic")
	}
}

// --- e2e: retrospective draft closes the narrative ---------------------------------

func TestPipelineRetrospectiveDraftClosesCluster(t *testing.T) {
	p, agents, _, _, _, _, _ := newPipeline(t)
	officialAgents(t, agents)
	matchID := uuid.NewString()

	// Build the story up: observe → track (drafting states).
	for _, tt := range []string{"pressure_building", "dominance_pattern"} {
		ev := trendEvent(tt, "pulse")
		ev.MatchID = matchID
		if _, err := p.HandleTrend(context.Background(),
			trend.Envelope{SchemaVersion: "v3", Trend: ev}); err != nil {
			t.Fatal(err)
		}
	}
	// Confirmed trend → confirmation draft AND the cluster completes
	// via the lifecycle engine.
	ev := trendEvent("momentum_shift", "pulse")
	ev.MatchID = matchID
	ev.LifecycleState = "confirmed"
	result, err := p.HandleTrend(context.Background(),
		trend.Envelope{SchemaVersion: "v3", Trend: ev})
	if err != nil {
		t.Fatal(err)
	}
	if result.Cluster.State != cluster.ClusterCompleted {
		t.Errorf("confirmed lifecycle must complete the cluster: %s", result.Cluster.State)
	}
	// The NEXT pulse trend opens a fresh narrative.
	ev2 := trendEvent("pressure_building", "pulse")
	ev2.MatchID = matchID
	next, err := p.HandleTrend(context.Background(),
		trend.Envelope{SchemaVersion: "v3", Trend: ev2})
	if err != nil {
		t.Fatal(err)
	}
	if next.Cluster.ID == result.Cluster.ID {
		t.Error("a completed narrative must never absorb new trends")
	}
	// And its evolution restarts at INITIAL_OBSERVATION.
	if len(next.Drafts) != 1 || next.Drafts[0].Metadata["draft_type"] != "initial_observation" {
		t.Errorf("fresh narrative must restart evolution: %+v", next.Drafts)
	}
}
