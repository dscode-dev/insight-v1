// Package decision — publication decisions.
//
// Determines whether communication should exist at all. Every decision
// is persisted with its full reasoning — no black-box decisions.
package decision

import (
	"time"

	"github.com/google/uuid"
)

// Action — what Nexus does with a routed trend.
type Action string

const (
	ActionIgnore       Action = "IGNORE"
	ActionMemoryOnly   Action = "MEMORY_ONLY"
	ActionDraft        Action = "DRAFT"
	ActionHighPriority Action = "HIGH_PRIORITY_DRAFT"
	ActionGlobal       Action = "GLOBAL_CANDIDATE"
)

// Drafts reports whether the action produces a draft.
func (a Action) Drafts() bool {
	return a == ActionDraft || a == ActionHighPriority || a == ActionGlobal
}

// Remembers reports whether the action writes agent memory (everything
// except a hard ignore — even memory-only observations feed continuity).
func (a Action) Remembers() bool { return a != ActionIgnore }

// Priority — the communication priority band (feed-readiness metadata).
type Priority string

const (
	PriorityLow      Priority = "LOW"
	PriorityMedium   Priority = "MEDIUM"
	PriorityHigh     Priority = "HIGH"
	PriorityCritical Priority = "CRITICAL"
)

// PublicationDecision is the persisted verdict for one (agent, trend).
type PublicationDecision struct {
	ID         uuid.UUID
	AgentID    uuid.UUID
	TrendID    string
	ClusterID  uuid.UUID
	MatchID    string
	Action     Action
	Priority   Priority
	Reasoning  []string
	Confidence float64
	CreatedAt  time.Time
}
