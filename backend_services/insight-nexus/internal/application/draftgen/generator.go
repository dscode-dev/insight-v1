// Package draftgen — the Draft Generator.
//
// Produces STRUCTURED communication drafts: deterministic projections
// of Atlas's trend contract + the agent's memory context. Explicitly
// out of scope (future sprints): social posts, Azteca feed content,
// any LLM generation. Every field below is reproducible from inputs.
package draftgen

import (
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-nexus/internal/application/contextbuilder"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
)

// Clock seam so tests pin draft timestamps.
type Clock func() time.Time

type Generator struct {
	now Clock
}

func New(now Clock) *Generator {
	if now == nil {
		now = time.Now
	}
	return &Generator{now: now}
}

// Generate builds one structured draft from a DraftContext.
func (g *Generator) Generate(dc contextbuilder.DraftContext) draft.Draft {
	ev := dc.Trend
	highlights := buildHighlights(dc)

	charts := make([]map[string]any, 0, 1)
	if len(ev.ChartData) > 0 {
		charts = append(charts, ev.ChartData)
	}

	metadata := map[string]any{
		"agent":            dc.Agent.Name,
		"specialty":        dc.Agent.Specialty,
		"trend_type":       ev.TrendType,
		"category":         ev.Category,
		"severity":         ev.Severity,
		"publication_tier": ev.PublicationTier,
		"meaning":          ev.Meaning,
		"meaning_category": ev.MeaningCategory,
		"lifecycle_state":  ev.LifecycleState,
		"correlation_ids":  ev.CorrelationIDs,
		"signals":          ev.Signals,
		"metrics":          ev.Metrics,
		"memory_count":     len(dc.Memories),
		"related_count":    len(dc.Related),
		"schema_version":   ev.SchemaVersion,
		// ---- Sprint 3: feed-readiness metadata (consumed later by
		// Atrium — no posting/feed integration in this sprint).
		"visibility":   string(visibilityFor(dc)),
		"priority":     priorityLabel(dc),
		"draft_type":   lower(dc.DraftType),
		"agent_state":  lower(dc.AgentState),
		"cluster_type": lower(dc.ClusterType),
		"cluster_id":   dc.ClusterID.String(),
		"sequence":     dc.Sequence,
		"action":       dc.Action,
	}
	if ev.PublishScore != nil {
		metadata["publish_score"] = *ev.PublishScore
	}
	if len(ev.Pattern) > 0 {
		metadata["pattern"] = ev.Pattern
	}

	return draft.Draft{
		ID:         uuid.New(),
		AgentID:    dc.Agent.ID,
		TrendID:    ev.TrendID,
		MatchID:    ev.MatchID,
		Title:      ev.Title,
		Summary:    ev.Summary,
		Highlights: highlights,
		Charts:     charts,
		Metadata:   metadata,
		Status:     draft.StatusGenerated,
		CreatedAt:  g.now().UTC(),
	}
}

// buildHighlights — the deterministic bullet facts a future content
// layer can render. Order is stable: meaning → lifecycle → pattern →
// continuity.
func buildHighlights(dc contextbuilder.DraftContext) []string {
	ev := dc.Trend
	out := make([]string, 0, 4)
	if ev.Meaning != "" {
		out = append(out, fmt.Sprintf("meaning: %s", ev.Meaning))
	}
	if ev.LifecycleState != "" {
		if prev := ev.PreviousStates(); len(prev) > 0 {
			out = append(out, fmt.Sprintf(
				"lifecycle: %s (was: %s)", ev.LifecycleState, joinStates(prev)))
		} else {
			out = append(out, fmt.Sprintf("lifecycle: %s", ev.LifecycleState))
		}
	}
	if occ, ok := numeric(ev.Pattern["occurrences"]); ok && occ > 0 {
		if rate, ok := numeric(ev.Pattern["historical_success_rate"]); ok {
			out = append(out, fmt.Sprintf(
				"pattern: seen %d time(s) before, %.0f%% confirmed",
				int(occ), rate*100))
		} else {
			out = append(out, fmt.Sprintf("pattern: seen %d time(s) before", int(occ)))
		}
	}
	if continuity := latestMemory(dc.Memories); continuity != "" {
		out = append(out, fmt.Sprintf("continuity: %s", continuity))
	}
	// Story-cluster continuity across matches (Sprint 3).
	if related := latestMemory(dc.Related); related != "" && related != latestMemory(dc.Memories) {
		out = append(out, fmt.Sprintf("related: %s", related))
	}
	// Narrative position (Sprint 3 evolution).
	if dc.DraftType != "" {
		out = append(out, fmt.Sprintf(
			"evolution: %s (#%d in %s story)",
			lower(dc.DraftType), dc.Sequence, lower(dc.ClusterType)))
	}
	return out
}

func latestMemory(memories []memory.Memory) string {
	if len(memories) == 0 {
		return ""
	}
	return memories[0].Summary
}

func joinStates(states []string) string {
	s := ""
	for i, st := range states {
		if i > 0 {
			s += " → "
		}
		s += st
	}
	return s
}

func numeric(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case int:
		return float64(n), true
	default:
		return 0, false
	}
}

// Visibility — feed-readiness visibility band (consumed later by
// Atrium; deterministic, never user-targeting).
type Visibility string

const (
	VisibilityPrivate     Visibility = "private"
	VisibilityCompetition Visibility = "competition"
	VisibilityGlobal      Visibility = "global"
)

// visibilityFor — deterministic visibility rule:
//
//	GLOBAL_CANDIDATE          → global
//	RETROSPECTIVE draft type  → private (post-event analysis)
//	everything else           → competition
func visibilityFor(dc contextbuilder.DraftContext) Visibility {
	if dc.Action == "GLOBAL_CANDIDATE" {
		return VisibilityGlobal
	}
	if dc.DraftType == "RETROSPECTIVE" {
		return VisibilityPrivate
	}
	return VisibilityCompetition
}

// priorityLabel — the decision engine's priority band, lowercased for
// the metadata contract; falls back to the stream priority flag for
// contexts that skipped the decision engine.
func priorityLabel(dc contextbuilder.DraftContext) string {
	if dc.Priority != "" {
		return lower(dc.Priority)
	}
	if dc.StreamPriority {
		return "high"
	}
	return "medium"
}

func lower(s string) string {
	out := make([]byte, len(s))
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			c += 'a' - 'A'
		}
		out[i] = c
	}
	return string(out)
}
