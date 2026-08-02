// Package agentstate — the Agent State Engine.
//
// Maintains one persisted narrative state per (agent, match, cluster)
// and advances it deterministically as the story develops:
//
//	IDLE → OBSERVING → TRACKING → ALERTING → RETROSPECTIVE
//
// Every transition is recorded on the state's history (auditable) and
// counted. The engine never decides WHETHER to communicate (the
// publication engine does) — it tracks WHERE the agent is in the
// story's arc.
package agentstate

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	"github.com/konoha-labs/insight-nexus/internal/domain/state"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

var agentStateTransitionsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
	Name: "agent_state_transitions_total",
	Help: "Agent narrative state transitions.",
}, []string{"from", "to"})

type Engine struct {
	states ports.AgentStateRepository
	now    func() time.Time
}

func New(states ports.AgentStateRepository, now func() time.Time) *Engine {
	if now == nil {
		now = time.Now
	}
	return &Engine{states: states, now: now}
}

// Advance loads (or opens) the agent's state for the cluster, applies
// the deterministic transition for this tick, persists, and returns
// the resulting state.
func (e *Engine) Advance(
	ctx context.Context,
	agentID uuid.UUID,
	c cluster.TrendCluster,
	d decision.PublicationDecision,
	ev trend.Event,
) (state.AgentState, error) {
	now := e.now().UTC()
	current, err := e.states.Get(ctx, agentID, c.MatchID, c.ID)
	if errors.Is(err, ports.ErrNotFound) {
		current = state.AgentState{
			ID:          uuid.New(),
			AgentID:     agentID,
			MatchID:     c.MatchID,
			ClusterID:   c.ID,
			ClusterType: string(c.ClusterType),
			Current:     state.Idle,
			CreatedAt:   now,
			UpdatedAt:   now,
		}
	} else if err != nil {
		return state.AgentState{}, fmt.Errorf("agentstate: get: %w", err)
	}

	next, reason := nextState(current.Current, d, ev)
	if current.Apply(next, reason, now) {
		agentStateTransitionsTotal.WithLabelValues(
			string(historyFrom(current)), string(next)).Inc()
	}
	if err := e.states.Save(ctx, current); err != nil {
		return state.AgentState{}, fmt.Errorf("agentstate: save: %w", err)
	}
	return current, nil
}

// nextState — the deterministic transition table.
//
//	terminal lifecycle (confirmed/failed/expired) while engaged
//	    → RETROSPECTIVE (post-event analysis)
//	critical decision (HIGH_PRIORITY / GLOBAL)
//	    → ALERTING
//	first sight of the story (from IDLE, any non-ignore action)
//	    → OBSERVING
//	story develops while OBSERVING (or de-escalates from ALERTING)
//	    → TRACKING
//	otherwise the state holds.
func nextState(
	current state.State, d decision.PublicationDecision, ev trend.Event,
) (state.State, string) {
	terminal := ev.LifecycleState == "confirmed" ||
		ev.LifecycleState == "failed" || ev.LifecycleState == "expired"
	if terminal && (current == state.Tracking || current == state.Alerting) {
		return state.Retrospective, "lifecycle=" + ev.LifecycleState
	}
	if d.Action == decision.ActionHighPriority || d.Action == decision.ActionGlobal {
		return state.Alerting, "action=" + string(d.Action)
	}
	if d.Action == decision.ActionIgnore {
		return current, "action=IGNORE (hold)"
	}
	switch current {
	case state.Idle:
		return state.Observing, "first_detection"
	case state.Observing:
		return state.Tracking, "story_evolving"
	case state.Alerting:
		return state.Tracking, "de_escalated"
	default:
		return current, "hold"
	}
}

// historyFrom — the From of the just-applied transition (for metrics).
func historyFrom(s state.AgentState) state.State {
	if len(s.History) == 0 {
		return state.Idle
	}
	return s.History[len(s.History)-1].From
}
