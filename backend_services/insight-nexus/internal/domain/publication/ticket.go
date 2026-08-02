package publication

import (
	"time"

	"github.com/google/uuid"
)

// TicketStatus — the human-review lifecycle (Part 15).
type TicketStatus string

const (
	TicketOpen        TicketStatus = "OPEN"
	TicketUnderReview TicketStatus = "UNDER_REVIEW"
	TicketApproved    TicketStatus = "APPROVED"
	TicketRejected    TicketStatus = "REJECTED"
	TicketPublished   TicketStatus = "PUBLISHED"
)

// ValidTicketTransition enforces the review state machine.
func ValidTicketTransition(from, to TicketStatus) bool {
	switch from {
	case TicketOpen:
		return to == TicketUnderReview || to == TicketRejected
	case TicketUnderReview:
		return to == TicketApproved || to == TicketRejected
	case TicketApproved:
		return to == TicketPublished || to == TicketRejected
	default:
		return false
	}
}

// Ticket — the all-providers-failed fallback (Part 14). NEVER an
// auto-publication: it carries everything a human admin needs to
// publish manually through the Console.
type Ticket struct {
	ID        uuid.UUID `json:"id"`
	AgentID   uuid.UUID `json:"agent_id"`
	AgentName string    `json:"agent_name"`

	TrendIDs  []string  `json:"trend_ids"`
	ClusterID uuid.UUID `json:"cluster_id"`
	// Context — the publication context snapshot (cluster type, match,
	// action, priority band, agent state, draft type, sequence).
	Context map[string]any `json:"context"`

	PublicationReason string `json:"publication_reason"`
	// Suggested content from the DETERMINISTIC draft layer (never an
	// LLM template) — complete enough for manual publication.
	SuggestedTitle   string `json:"suggested_title"`
	SuggestedSummary string `json:"suggested_summary"`
	// Evidence — the structured supporting facts (draft highlights).
	Evidence []string `json:"evidence"`
	Priority string   `json:"priority"`
	MatchID  string   `json:"match_id"`

	Status      TicketStatus `json:"status"`
	ReviewedBy  string       `json:"reviewed_by"`
	ReviewedAt  *time.Time   `json:"reviewed_at"`
	PublishedBy string       `json:"published_by"`
	PublishedAt *time.Time   `json:"published_at"`

	CreatedAt time.Time `json:"created_at"`
}
