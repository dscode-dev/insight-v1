// Package memory — agent continuity memory.
//
// One row per (agent, trend) observation: a short deterministic
// summary of what the agent saw, so tomorrow's context can reference
// yesterday's observation ("Ninja detected increasing confidence")
// without any historical event queries.
package memory

import (
	"errors"
	"time"

	"github.com/google/uuid"
)

var (
	ErrMissingAgent   = errors.New("memory: agent_id required")
	ErrMissingSummary = errors.New("memory: summary required")
)

// Kind — what the memory records (Sprint 4 Part 8 expansion).
type Kind string

const (
	// KindObservation — the agent saw a trend (Sprint 2 behaviour).
	KindObservation Kind = "observation"
	// KindPublication — the agent PUBLISHED about a story. The
	// repetition guard reads these: "I already posted about this."
	KindPublication Kind = "publication"
)

// Memory is one persisted agent observation or publication.
type Memory struct {
	ID      uuid.UUID
	AgentID uuid.UUID
	MatchID string
	TrendID string
	// ClusterType — which story this memory belongs to (Sprint 3).
	// Enables related-memory retrieval for narrative continuity.
	ClusterType string
	// ClusterID — the concrete story instance (Sprint 4). Lets the
	// publisher ask "did I publish about THIS cluster?".
	ClusterID uuid.UUID
	// Kind — observation (default) or publication.
	Kind    Kind
	Summary string
	// Narrative — for publications: the published title (previous
	// narratives feed the anti-repetition prompt + duplicate guard).
	Narrative string
	CreatedAt time.Time
}

func (m Memory) Validate() error {
	if m.AgentID == uuid.Nil {
		return ErrMissingAgent
	}
	if m.Summary == "" {
		return ErrMissingSummary
	}
	return nil
}
