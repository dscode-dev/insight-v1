// Package state — agent narrative state.
//
// Agents are stateful: one active state per (agent, match, cluster)
// tracks where the agent is in that story's narrative arc. Transitions
// are deterministic, stored, auditable.
package state

import (
	"time"

	"github.com/google/uuid"
)

// State — the agent's narrative posture for one story.
type State string

const (
	Idle          State = "IDLE"          // no active narrative
	Observing     State = "OBSERVING"     // initial detection
	Tracking      State = "TRACKING"      // same topic evolving
	Alerting      State = "ALERTING"      // critical communication
	Retrospective State = "RETROSPECTIVE" // post-event analysis
)

// Transition is one audited state change.
type Transition struct {
	From   State  `json:"from"`
	To     State  `json:"to"`
	Reason string `json:"reason"`
	At     string `json:"at"` // RFC3339
}

// AgentState is the persisted narrative state for one
// (agent, match, cluster).
type AgentState struct {
	ID          uuid.UUID
	AgentID     uuid.UUID
	MatchID     string
	ClusterID   uuid.UUID
	ClusterType string
	Current     State
	History     []Transition
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// Apply records a transition (no-op when the state is unchanged).
// Returns whether a transition actually happened.
func (s *AgentState) Apply(to State, reason string, now time.Time) bool {
	if s.Current == to {
		s.UpdatedAt = now
		return false
	}
	s.History = append(s.History, Transition{
		From:   s.Current,
		To:     to,
		Reason: reason,
		At:     now.UTC().Format(time.RFC3339),
	})
	s.Current = to
	s.UpdatedAt = now
	return true
}
