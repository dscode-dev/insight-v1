// Package publication — the Publication Decision Engine.
//
// Determines whether communication should exist at all. Pure +
// deterministic: the decision is a rule cascade over Atlas's
// evaluation fields (tier, score, lifecycle, correlations, pattern)
// plus Nexus-side context (agent draft history in the cluster, trend
// age). Every decision carries its full reasoning trail and is
// persisted by the pipeline — no black-box decisions.
//
// The engine NEVER re-derives intelligence: it consumes Atlas's
// verdicts and only decides communication policy on top of them.
package publication

import (
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
)

var (
	publicationDecisionsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "publication_decisions_total",
		Help: "Publication decisions, by action.",
	}, []string{"action"})
	globalCandidatesTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "global_candidates_total",
		Help: "Trends elevated to global communication candidates.",
	})
)

// Config — every threshold is tunable at composition time.
type Config struct {
	// MaxDraftsPerCluster — once an agent has drafted a story this many
	// times, further activity becomes memory-only (anti-repetition;
	// the evolution engine governs variety below this cap).
	MaxDraftsPerCluster int
	// StaleAge — trends older than this on arrival are demoted one
	// level (late replays should not alert anyone).
	StaleAge time.Duration
	// PatternBoostOccurrences / PatternBoostRate — a known recurring
	// pattern with a strong success history adds confidence.
	PatternBoostOccurrences int
	PatternBoostRate        float64
}

func (c Config) defaults() Config {
	if c.MaxDraftsPerCluster <= 0 {
		c.MaxDraftsPerCluster = 10
	}
	if c.StaleAge <= 0 {
		c.StaleAge = 30 * time.Minute
	}
	if c.PatternBoostOccurrences <= 0 {
		c.PatternBoostOccurrences = 3
	}
	if c.PatternBoostRate <= 0 {
		c.PatternBoostRate = 0.7
	}
	return c
}

// Inputs — everything the decision considers.
type Inputs struct {
	AgentID   uuid.UUID
	MatchID   string
	ClusterID uuid.UUID
	Trend     trend.Event
	Priority  bool // Atlas stream priority flag
	// AgentDraftCount — drafts this agent already produced in the
	// trend's cluster (Nexus history).
	AgentDraftCount int
	Now             time.Time
}

type Engine struct {
	cfg Config
}

func New(cfg Config) *Engine {
	return &Engine{cfg: cfg.defaults()}
}

// Decide — the deterministic rule cascade.
func (e *Engine) Decide(in Inputs) decision.PublicationDecision {
	ev := in.Trend
	reasoning := make([]string, 0, 6)

	// 1. Base action from Atlas's publication tier.
	action := baseAction(ev.PublicationTier)
	reasoning = append(reasoning,
		fmt.Sprintf("atlas_tier=%s -> %s", orUnknown(ev.PublicationTier), action))

	// 2. Dead narratives never publish: failed/expired lifecycle
	// downgrades to ignore (the memory of them already exists).
	if ev.LifecycleState == "failed" || ev.LifecycleState == "expired" {
		action = decision.ActionIgnore
		reasoning = append(reasoning,
			fmt.Sprintf("lifecycle=%s -> IGNORE", ev.LifecycleState))
	}

	// 3. Correlated critical trend → global candidate.
	if action == decision.ActionHighPriority &&
		len(ev.CorrelationIDs) > 0 && ev.Severity == "critical" {
		action = decision.ActionGlobal
		globalCandidatesTotal.Inc()
		reasoning = append(reasoning,
			fmt.Sprintf("correlated_critical(correlations=%d) -> GLOBAL_CANDIDATE",
				len(ev.CorrelationIDs)))
	}

	// 4. Anti-repetition: cluster draft budget exhausted → memory only.
	if action.Drafts() && in.AgentDraftCount >= e.cfg.MaxDraftsPerCluster {
		action = decision.ActionMemoryOnly
		reasoning = append(reasoning,
			fmt.Sprintf("cluster_draft_budget_exhausted(%d/%d) -> MEMORY_ONLY",
				in.AgentDraftCount, e.cfg.MaxDraftsPerCluster))
	}

	// 5. Stale trend age demotes one level.
	if age, ok := trendAge(ev, in.Now); ok && age > e.cfg.StaleAge && action.Drafts() {
		action = demote(action)
		reasoning = append(reasoning,
			fmt.Sprintf("stale_trend(age=%s) -> %s", age.Round(time.Minute), action))
	}

	// 6. Confidence: Atlas's publish score, boosted by lifecycle +
	// pattern recurrence.
	confidence := baseConfidence(ev)
	if ev.LifecycleState == "confirmed" {
		confidence = clamp(confidence + 0.1)
		reasoning = append(reasoning, "lifecycle=confirmed (+0.10 confidence)")
	}
	if occ, rate, ok := patternStats(ev); ok &&
		occ >= e.cfg.PatternBoostOccurrences && rate >= e.cfg.PatternBoostRate {
		confidence = clamp(confidence + 0.05)
		reasoning = append(reasoning,
			fmt.Sprintf("pattern_recurrence(occurrences=%d rate=%.2f) (+0.05 confidence)",
				occ, rate))
	}

	d := decision.PublicationDecision{
		ID:         uuid.New(),
		AgentID:    in.AgentID,
		TrendID:    ev.TrendID,
		ClusterID:  in.ClusterID,
		MatchID:    in.MatchID,
		Action:     action,
		Priority:   priorityFor(action, ev.Severity),
		Reasoning:  reasoning,
		Confidence: confidence,
		CreatedAt:  in.Now.UTC(),
	}
	publicationDecisionsTotal.WithLabelValues(string(action)).Inc()
	return d
}

func baseAction(tier string) decision.Action {
	switch tier {
	case "suppress":
		return decision.ActionIgnore
	case "store_only":
		return decision.ActionMemoryOnly
	case "publish":
		return decision.ActionDraft
	case "priority_publish":
		return decision.ActionHighPriority
	default:
		// v1/v2 producers without a tier: conservative default.
		return decision.ActionMemoryOnly
	}
}

func demote(a decision.Action) decision.Action {
	switch a {
	case decision.ActionGlobal:
		return decision.ActionHighPriority
	case decision.ActionHighPriority:
		return decision.ActionDraft
	case decision.ActionDraft:
		return decision.ActionMemoryOnly
	default:
		return a
	}
}

func priorityFor(a decision.Action, severity string) decision.Priority {
	switch a {
	case decision.ActionGlobal:
		return decision.PriorityCritical
	case decision.ActionHighPriority:
		if severity == "critical" {
			return decision.PriorityCritical
		}
		return decision.PriorityHigh
	case decision.ActionDraft:
		return decision.PriorityMedium
	default:
		return decision.PriorityLow
	}
}

func baseConfidence(ev trend.Event) float64 {
	if ev.PublishScore != nil {
		return clamp(*ev.PublishScore)
	}
	return clamp(ev.Confidence)
}

func trendAge(ev trend.Event, now time.Time) (time.Duration, bool) {
	if ev.CreatedAt == "" {
		return 0, false
	}
	created, err := time.Parse(time.RFC3339, ev.CreatedAt)
	if err != nil {
		return 0, false
	}
	return now.Sub(created), true
}

func patternStats(ev trend.Event) (int, float64, bool) {
	occRaw, ok := ev.Pattern["occurrences"]
	if !ok {
		return 0, 0, false
	}
	occ, ok := toFloat(occRaw)
	if !ok {
		return 0, 0, false
	}
	rate, ok := toFloat(ev.Pattern["historical_success_rate"])
	if !ok {
		return int(occ), 0, false
	}
	return int(occ), rate, true
}

func toFloat(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case int:
		return float64(n), true
	default:
		return 0, false
	}
}

func clamp(v float64) float64 {
	if v < 0 {
		return 0
	}
	if v > 1 {
		return 1
	}
	return v
}

func orUnknown(s string) string {
	if s == "" {
		return "unknown"
	}
	return s
}
