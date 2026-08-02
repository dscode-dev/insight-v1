// Sprint 3 — communication intelligence: clustering, publication
// decisions, agent state machine, draft evolution, and the full
// funnel (trend → cluster → decision → state → evolution → draft).
package application_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-nexus/internal/adapters/inmemory"
	"github.com/konoha-labs/insight-nexus/internal/application/agentstate"
	"github.com/konoha-labs/insight-nexus/internal/application/clustering"
	"github.com/konoha-labs/insight-nexus/internal/application/evolution"
	"github.com/konoha-labs/insight-nexus/internal/application/publication"
	"github.com/konoha-labs/insight-nexus/internal/application/router"
	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	domainevolution "github.com/konoha-labs/insight-nexus/internal/domain/evolution"
	"github.com/konoha-labs/insight-nexus/internal/domain/state"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
)

var fixedNow = func() time.Time { return time.Date(2026, 6, 1, 10, 0, 0, 0, time.UTC) }

// --- clustering ----------------------------------------------------------------

func TestClusterTypeMappingCoversTaxonomy(t *testing.T) {
	cases := map[string]cluster.Type{
		"pressure_building":     cluster.AttackingPressure,
		"dominance_pattern":     cluster.AttackingPressure,
		"momentum_shift":        cluster.AttackingPressure,
		"market_conviction":     cluster.MarketConfidence,
		"market_anomaly":        cluster.MarketConfidence,
		"risk_escalation":       cluster.RiskEscalation,
		"impact_assessment":     cluster.RiskEscalation,
		"narrative_divergence":  cluster.NarrativeShift,
		"historical_deviation":  cluster.HistoricalRepeat,
		"historical_similarity": cluster.HistoricalRepeat,
	}
	for trendType, want := range cases {
		got, err := cluster.TypeFor(trendType, "")
		if err != nil || got != want {
			t.Errorf("%s → %v (err=%v), want %v", trendType, got, err, want)
		}
	}
	// Unknown future type resolves through its category.
	got, err := cluster.TypeFor("brand_new_market_thing", "ninja")
	if err != nil || got != cluster.MarketConfidence {
		t.Errorf("category fallback failed: %v %v", got, err)
	}
}

func TestClusteringOneStoryPerMatch(t *testing.T) {
	eng := clustering.New(inmemory.NewClusterRepo(), fixedNow, 90*time.Minute)
	matchID := uuid.NewString()

	pressure := trendEvent("pressure_building", "pulse")
	pressure.MatchID = matchID
	c1, created1, err := eng.Assign(context.Background(), pressure)
	if err != nil || !created1 {
		t.Fatalf("first trend must open the cluster: %v", err)
	}

	dominance := trendEvent("dominance_pattern", "pulse")
	dominance.MatchID = matchID
	dominance.Confidence = 0.95
	c2, created2, err := eng.Assign(context.Background(), dominance)
	if err != nil || created2 {
		t.Fatalf("second pulse trend must absorb, not create: %v", err)
	}
	if c1.ID != c2.ID {
		t.Error("same story must share one cluster")
	}
	if len(c2.TrendIDs) != 2 || len(c2.TrendTypes) != 2 {
		t.Errorf("absorption wrong: %+v", c2)
	}
	if c2.Confidence != 0.95 {
		t.Errorf("confidence must track the strongest member: %v", c2.Confidence)
	}

	// A market trend on the same match opens a DIFFERENT story.
	market := trendEvent("market_shift", "ninja")
	market.MatchID = matchID
	c3, created3, _ := eng.Assign(context.Background(), market)
	if !created3 || c3.ID == c1.ID {
		t.Error("different story must get its own cluster")
	}
}

// --- publication decisions --------------------------------------------------------

func decide(t *testing.T, mutate func(*trend.Event), draftCount int) decision.PublicationDecision {
	t.Helper()
	eng := publication.New(publication.Config{})
	ev := trendEvent("market_shift", "ninja")
	if mutate != nil {
		mutate(&ev)
	}
	return eng.Decide(publication.Inputs{
		AgentID:         uuid.New(),
		MatchID:         ev.MatchID,
		ClusterID:       uuid.New(),
		Trend:           ev,
		AgentDraftCount: draftCount,
		Now:             fixedNow(),
	})
}

func TestDecisionTierMapping(t *testing.T) {
	cases := map[string]decision.Action{
		"suppress":         decision.ActionIgnore,
		"store_only":       decision.ActionMemoryOnly,
		"publish":          decision.ActionDraft,
		"priority_publish": decision.ActionHighPriority,
	}
	for tier, want := range cases {
		d := decide(t, func(ev *trend.Event) { ev.PublicationTier = tier }, 0)
		if d.Action != want {
			t.Errorf("tier %s → %s, want %s", tier, d.Action, want)
		}
		if len(d.Reasoning) == 0 {
			t.Error("no black-box decisions: reasoning required")
		}
	}
}

func TestDecisionGlobalCandidate(t *testing.T) {
	d := decide(t, func(ev *trend.Event) {
		ev.PublicationTier = "priority_publish"
		ev.Severity = "critical"
		ev.CorrelationIDs = []string{uuid.NewString()}
	}, 0)
	if d.Action != decision.ActionGlobal {
		t.Errorf("correlated critical must be GLOBAL_CANDIDATE: %s", d.Action)
	}
	if d.Priority != decision.PriorityCritical {
		t.Errorf("global candidate priority: %s", d.Priority)
	}
}

func TestDecisionDeadNarrativesIgnored(t *testing.T) {
	for _, lc := range []string{"failed", "expired"} {
		d := decide(t, func(ev *trend.Event) {
			ev.PublicationTier = "priority_publish"
			ev.LifecycleState = lc
		}, 0)
		if d.Action != decision.ActionIgnore {
			t.Errorf("lifecycle %s must IGNORE: %s", lc, d.Action)
		}
	}
}

func TestDecisionClusterBudgetExhaustion(t *testing.T) {
	d := decide(t, nil, 10) // default MaxDraftsPerCluster
	if d.Action != decision.ActionMemoryOnly {
		t.Errorf("exhausted budget must demote to MEMORY_ONLY: %s", d.Action)
	}
	joined := strings.Join(d.Reasoning, "|")
	if !strings.Contains(joined, "budget_exhausted") {
		t.Errorf("reasoning must explain the demotion: %v", d.Reasoning)
	}
}

func TestDecisionStaleTrendDemoted(t *testing.T) {
	d := decide(t, func(ev *trend.Event) {
		ev.PublicationTier = "priority_publish"
		ev.CreatedAt = "2026-06-01T09:00:00Z" // 60 min old vs fixedNow
	}, 0)
	if d.Action != decision.ActionDraft {
		t.Errorf("stale priority trend must demote one level: %s", d.Action)
	}
}

func TestDecisionPatternBoostsConfidence(t *testing.T) {
	base := decide(t, func(ev *trend.Event) { ev.Pattern = nil }, 0)
	boosted := decide(t, func(ev *trend.Event) {
		ev.Pattern = map[string]any{
			"occurrences": float64(4), "historical_success_rate": 0.72,
		}
	}, 0)
	if boosted.Confidence <= base.Confidence {
		t.Errorf("pattern recurrence must boost confidence: %v vs %v",
			boosted.Confidence, base.Confidence)
	}
}

// --- agent state machine -----------------------------------------------------------

func advance(t *testing.T, eng *agentstate.Engine, agentID uuid.UUID,
	c cluster.TrendCluster, action decision.Action, lifecycle string) state.AgentState {
	t.Helper()
	ev := trendEvent("pressure_building", "pulse")
	ev.MatchID = c.MatchID
	ev.LifecycleState = lifecycle
	s, err := eng.Advance(context.Background(), agentID, c,
		decision.PublicationDecision{Action: action}, ev)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestAgentStateNarrativeArc(t *testing.T) {
	eng := agentstate.New(inmemory.NewAgentStateRepo(), fixedNow)
	agentID := uuid.New()
	c := cluster.TrendCluster{
		ID: uuid.New(), MatchID: uuid.NewString(),
		ClusterType: cluster.AttackingPressure,
	}

	// IDLE → OBSERVING (initial detection, even memory-only).
	s := advance(t, eng, agentID, c, decision.ActionMemoryOnly, "active")
	if s.Current != state.Observing {
		t.Fatalf("first detection: %s", s.Current)
	}
	// OBSERVING → TRACKING (story evolving).
	s = advance(t, eng, agentID, c, decision.ActionDraft, "strengthening")
	if s.Current != state.Tracking {
		t.Fatalf("evolving story: %s", s.Current)
	}
	// TRACKING → ALERTING (critical communication).
	s = advance(t, eng, agentID, c, decision.ActionHighPriority, "strengthening")
	if s.Current != state.Alerting {
		t.Fatalf("critical: %s", s.Current)
	}
	// ALERTING → RETROSPECTIVE (post-event).
	s = advance(t, eng, agentID, c, decision.ActionDraft, "confirmed")
	if s.Current != state.Retrospective {
		t.Fatalf("post-event: %s", s.Current)
	}
	// The full arc is audited.
	if len(s.History) != 4 {
		t.Errorf("expected 4 audited transitions, got %d: %+v", len(s.History), s.History)
	}
	if s.History[0].From != state.Idle || s.History[0].To != state.Observing {
		t.Errorf("first transition wrong: %+v", s.History[0])
	}
}

// --- draft evolution -----------------------------------------------------------------

func TestEvolutionNarrativeSequence(t *testing.T) {
	repo := inmemory.NewEvolutionRepo()
	eng := evolution.New(repo, fixedNow)
	ctx := context.Background()
	agentID, clusterID := uuid.New(), uuid.New()
	matchID := uuid.NewString()
	ev := trendEvent("pressure_building", "pulse")

	classify := func(st state.State, lifecycle string) evolution.Classification {
		t.Helper()
		ev.LifecycleState = lifecycle
		class, err := eng.Classify(ctx, agentID, clusterID, st, ev)
		if err != nil {
			t.Fatal(err)
		}
		if err := eng.Record(ctx, agentID, clusterID, uuid.New(), matchID, class); err != nil {
			t.Fatal(err)
		}
		return class
	}

	first := classify(state.Observing, "active")
	if first.DraftType != domainevolution.InitialObservation || first.Sequence != 1 {
		t.Errorf("first draft: %+v", first)
	}
	second := classify(state.Tracking, "strengthening")
	if second.DraftType != domainevolution.FollowUp || second.Sequence != 2 {
		t.Errorf("second draft: %+v", second)
	}
	third := classify(state.Tracking, "confirmed")
	if third.DraftType != domainevolution.Confirmation || third.Sequence != 3 {
		t.Errorf("confirmed draft: %+v", third)
	}
	fourth := classify(state.Retrospective, "confirmed")
	if fourth.DraftType != domainevolution.Retrospective || fourth.Sequence != 4 {
		t.Errorf("retrospective draft: %+v", fourth)
	}
}

// --- the full communication funnel ---------------------------------------------------

func TestFunnelSameStoryEvolvesInsteadOfRepeating(t *testing.T) {
	p, agents, _, drafts, _, _, _ := newPipeline(t)
	officialAgents(t, agents)
	matchID := uuid.NewString()

	send := func(trendType string) {
		t.Helper()
		ev := trendEvent(trendType, "pulse")
		ev.MatchID = matchID
		if _, err := p.HandleTrend(context.Background(),
			trend.Envelope{SchemaVersion: "v3", Trend: ev}); err != nil {
			t.Fatal(err)
		}
	}

	// Three trends describing ONE attacking-pressure story.
	send("pressure_building")
	send("dominance_pattern")
	send("momentum_shift")

	all := drafts.All()
	if len(all) != 3 {
		t.Fatalf("expected 3 drafts, got %d", len(all))
	}
	// NOT three identical communications: the story evolves.
	types := []string{}
	for _, d := range all {
		types = append(types, d.Metadata["draft_type"].(string))
	}
	if types[0] != "initial_observation" || types[1] != "follow_up" || types[2] != "follow_up" {
		t.Errorf("story must evolve, got %v", types)
	}
	// All three drafts share one cluster.
	clusterIDs := map[string]bool{}
	for _, d := range all {
		clusterIDs[d.Metadata["cluster_id"].(string)] = true
	}
	if len(clusterIDs) != 1 {
		t.Errorf("one story must mean one cluster: %v", clusterIDs)
	}
	// Sequence advances.
	if all[2].Metadata["sequence"] != 3 {
		t.Errorf("sequence must advance: %v", all[2].Metadata["sequence"])
	}
}

func TestFunnelSuppressedTierNeverDrafts(t *testing.T) {
	p, agents, memories, drafts, _, _, _ := newPipeline(t)
	seeded := officialAgents(t, agents)
	ev := trendEvent("market_shift", "ninja")
	ev.PublicationTier = "store_only"
	result, err := p.HandleTrend(context.Background(),
		trend.Envelope{SchemaVersion: "v3", Trend: ev})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Drafts) != 0 || len(drafts.All()) != 0 {
		t.Error("store_only must not draft")
	}
	if len(result.Decisions) != 1 || result.Decisions[0].Action != decision.ActionMemoryOnly {
		t.Errorf("decision missing/wrong: %+v", result.Decisions)
	}
	// But the observation still feeds continuity.
	mems, _ := memories.Recent(context.Background(), seeded["ninja"].ID, ev.MatchID, 10)
	if len(mems) != 1 {
		t.Errorf("memory-only action must store memory: %d", len(mems))
	}
}

func TestFunnelGlobalCandidatePriorityQueue(t *testing.T) {
	p, agents, _, _, pubs, _, _ := newPipeline(t)
	officialAgents(t, agents)
	ev := trendEvent("risk_escalation", "fusion")
	ev.PublicationTier = "priority_publish"
	ev.Severity = "critical"
	ev.CorrelationIDs = []string{uuid.NewString()}
	result, err := p.HandleTrend(context.Background(),
		trend.Envelope{SchemaVersion: "v3", Priority: true, Trend: ev})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Drafts) != 1 {
		t.Fatalf("expected one sentinel draft: %+v", result)
	}
	d := result.Drafts[0]
	if d.Metadata["visibility"] != "global" {
		t.Errorf("global candidate must be globally visible: %v", d.Metadata["visibility"])
	}
	if d.Metadata["priority"] != "critical" {
		t.Errorf("priority band: %v", d.Metadata["priority"])
	}
	cands := pubs.All()
	if len(cands) != 1 || !cands[0].Priority {
		t.Errorf("global candidate must enqueue with priority: %+v", cands)
	}
}

func TestRelatedMemoriesCrossMatchContinuity(t *testing.T) {
	p, agents, _, drafts, _, _, _ := newPipeline(t)
	officialAgents(t, agents)

	// Match 1: a market story plays out.
	ev1 := trendEvent("market_shift", "ninja")
	if _, err := p.HandleTrend(context.Background(),
		trend.Envelope{SchemaVersion: "v3", Trend: ev1}); err != nil {
		t.Fatal(err)
	}
	// Match 2 (different match): the same KIND of story. The draft must
	// reference the related memory from match 1.
	ev2 := trendEvent("market_shift", "ninja")
	if _, err := p.HandleTrend(context.Background(),
		trend.Envelope{SchemaVersion: "v3", Trend: ev2}); err != nil {
		t.Fatal(err)
	}
	all := drafts.All()
	last := all[len(all)-1]
	joined := strings.Join(last.Highlights, "|")
	if !strings.Contains(joined, "related: market_shift") {
		t.Errorf("cross-match continuity missing: %v", last.Highlights)
	}
	if last.Metadata["related_count"].(int) < 1 {
		t.Errorf("related_count: %v", last.Metadata["related_count"])
	}
}

// Compile-time guard: the router stays interface-driven.
var _ = router.New
