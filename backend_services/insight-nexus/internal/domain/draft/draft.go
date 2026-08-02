// Package draft — structured communication drafts.
//
// A draft is what Nexus produces THIS sprint: a structured,
// machine-readable communication candidate. It is explicitly NOT a
// social post, NOT Azteca feed content, and contains NO LLM output —
// every field is deterministic projection of Atlas's trend contract
// plus agent memory context. Future sprints transform queued drafts
// into feed content.
package draft

import (
	"errors"
	"time"

	"github.com/google/uuid"
)

// Status — the draft lifecycle within Nexus.
type Status string

const (
	StatusGenerated Status = "generated"
	StatusQueued    Status = "queued"
)

var (
	ErrMissingAgent = errors.New("draft: agent_id required")
	ErrMissingTrend = errors.New("draft: trend_id required")
	ErrMissingTitle = errors.New("draft: title required")
)

// Draft is the structured communication candidate.
type Draft struct {
	ID      uuid.UUID
	AgentID uuid.UUID
	TrendID string
	MatchID string

	Title      string
	Summary    string
	Highlights []string
	Charts     []map[string]any
	Metadata   map[string]any

	Status    Status
	CreatedAt time.Time
}

func (d Draft) Validate() error {
	if d.AgentID == uuid.Nil {
		return ErrMissingAgent
	}
	if d.TrendID == "" {
		return ErrMissingTrend
	}
	if d.Title == "" {
		return ErrMissingTitle
	}
	return nil
}
