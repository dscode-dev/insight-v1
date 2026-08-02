// Package evolution — draft evolution.
//
// Prevents repetitive communication: the same story must evolve
// (initial observation → follow-up → confirmation → retrospective),
// never repeat ("pressure increasing" three times).
package evolution

import (
	"time"

	"github.com/google/uuid"
)

// DraftType — where a draft sits in its story's arc.
type DraftType string

const (
	InitialObservation DraftType = "INITIAL_OBSERVATION"
	FollowUp           DraftType = "FOLLOW_UP"
	Confirmation       DraftType = "CONFIRMATION"
	Retrospective      DraftType = "RETROSPECTIVE"
)

// Record is one persisted evolution step: which draft, in which
// cluster, at which sequence position, with which type.
type Record struct {
	ID        uuid.UUID
	AgentID   uuid.UUID
	ClusterID uuid.UUID
	DraftID   uuid.UUID
	MatchID   string
	DraftType DraftType
	Sequence  int // 1-based position in the cluster's narrative
	CreatedAt time.Time
}
