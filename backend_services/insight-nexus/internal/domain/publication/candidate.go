// Package publication — publication candidates + tickets (Sprint 4
// Parts 12–15).
//
// A Candidate is the fully-explainable record of one attempt to turn
// a draft into a Social post: every candidate stores the trend ids,
// cluster, decision, reason, prompt version, provider/model/fallback
// chain and draft version — the Console can always answer "why was
// this post published?" and "why was this one suppressed?".
package publication

import (
	"errors"
	"time"

	"github.com/google/uuid"
)

// CandidateStatus — the candidate lifecycle.
type CandidateStatus string

const (
	CandidatePublished  CandidateStatus = "PUBLISHED"
	CandidateSuppressed CandidateStatus = "SUPPRESSED" // anti-spam said no
	CandidateInvalid    CandidateStatus = "INVALID"    // validation said no
	CandidateFailed     CandidateStatus = "FAILED"     // social publish failed
	CandidateTicketed   CandidateStatus = "TICKETED"   // all providers failed
)

var ErrMissingAgent = errors.New("publication: agent required")

// Candidate is one explainable publication attempt. JSON tags are the
// admin API wire shape (Console reads candidates) — snake_case,
// additive-only.
type Candidate struct {
	ID        uuid.UUID `json:"id"`
	DraftID   uuid.UUID `json:"draft_id"`
	AgentID   uuid.UUID `json:"agent_id"`
	AgentName string    `json:"agent_name"`

	// ---- explainability (Part 12 — mandatory) ----
	TrendIDs          []string  `json:"trend_ids"`
	ClusterID         uuid.UUID `json:"cluster_id"`
	DecisionID        uuid.UUID `json:"decision_id"`
	PublicationReason string    `json:"publication_reason"`
	PromptVersion     string    `json:"prompt_version"`
	Provider          string    `json:"provider"`
	Model             string    `json:"model"`
	FallbackUsed      bool      `json:"fallback_used"`
	FallbackChain     []string  `json:"fallback_chain"`
	DraftVersion      int       `json:"draft_version"`

	// ---- composed content (Part 9 — Social post shape) ----
	Title      string   `json:"title"`
	Summary    string   `json:"summary"`
	Highlights []string `json:"highlights"`
	Tags       []string `json:"tags"`
	ChartHints []string `json:"chart_hints"`
	MatchID    string   `json:"match_id"`

	Status CandidateStatus `json:"status"`
	// StatusReason — REQUIRED for SUPPRESSED/INVALID/FAILED: every
	// suppression is explainable.
	StatusReason string `json:"status_reason"`
	SocialPostID string `json:"social_post_id"`

	CreatedAt   time.Time  `json:"created_at"`
	PublishedAt *time.Time `json:"published_at"`
}

func (c Candidate) Validate() error {
	if c.AgentID == uuid.Nil || c.AgentName == "" {
		return ErrMissingAgent
	}
	return nil
}
