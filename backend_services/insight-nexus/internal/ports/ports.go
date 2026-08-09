// Package ports — the contracts between Nexus's application layer and
// its adapters. Application code depends ONLY on these interfaces;
// concrete Postgres/Redis/HTTP implementations live under
// internal/adapters and are chosen at the composition root.
package ports

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/evolution"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/persona"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
	"github.com/konoha-labs/insight-nexus/internal/domain/state"
)

var (
	ErrNotFound  = errors.New("ports: not found")
	ErrDuplicate = errors.New("ports: duplicate")
)

// AgentRepository — persisted, editable agents. No hardcoded agents:
// the router reads this on every trend.
type AgentRepository interface {
	List(ctx context.Context) ([]agent.Agent, error)
	ListActive(ctx context.Context) ([]agent.Agent, error)
	Get(ctx context.Context, id uuid.UUID) (agent.Agent, error)
	Create(ctx context.Context, a agent.Agent) error
	Update(ctx context.Context, a agent.Agent) error
	SetActive(ctx context.Context, id uuid.UUID, active bool) error
}

// MemoryRepository — agent continuity memory.
type MemoryRepository interface {
	Save(ctx context.Context, m memory.Memory) error
	// Recent returns the newest-first memories for one agent on one
	// match (the context builder reads the last 10).
	Recent(ctx context.Context, agentID uuid.UUID, matchID string, limit int) ([]memory.Memory, error)
	// Related returns the agent's newest-first memories for one story
	// cluster type across ALL matches (Sprint 3 — narrative
	// continuity beyond the current match).
	Related(ctx context.Context, agentID uuid.UUID, clusterType string, limit int) ([]memory.Memory, error)
	// RecentPublications returns the agent's newest-first PUBLICATION
	// memories on one cluster (Sprint 4 — the repetition guard:
	// "I already posted about this story").
	RecentPublications(ctx context.Context, agentID uuid.UUID, clusterID uuid.UUID, limit int) ([]memory.Memory, error)
}

// ClusterRepository — one ACTIVE story cluster per (match, type).
// Closed clusters (COMPLETED/FAILED/EXPIRED) are never returned by
// GetActive — a new trend for the same story opens a FRESH cluster
// (Sprint 3.5 reopen behaviour).
type ClusterRepository interface {
	// GetActive returns the OPEN cluster for (match, type) or
	// ErrNotFound when no story is currently open.
	GetActive(ctx context.Context, matchID string, clusterType cluster.Type) (cluster.TrendCluster, error)
	// Save upserts the cluster (insert on first trend, full update on
	// absorption or closure).
	Save(ctx context.Context, c cluster.TrendCluster) error
	// ListActiveByMatch — every open cluster on one match (the match
	// end sweep closes them).
	ListActiveByMatch(ctx context.Context, matchID string) ([]cluster.TrendCluster, error)
	// List — newest-first, for the audit API.
	List(ctx context.Context, limit int) ([]cluster.TrendCluster, error)
}

// DecisionRepository — every publication decision is stored.
// No black-box decisions.
type DecisionRepository interface {
	Record(ctx context.Context, d decision.PublicationDecision) error
	List(ctx context.Context, limit int) ([]decision.PublicationDecision, error)
}

// AgentStateRepository — one active narrative state per
// (agent, match, cluster).
type AgentStateRepository interface {
	// Get returns ErrNotFound when the agent has no state for the
	// cluster yet (i.e. IDLE).
	Get(ctx context.Context, agentID uuid.UUID, matchID string, clusterID uuid.UUID) (state.AgentState, error)
	Save(ctx context.Context, s state.AgentState) error
	// ListByAgent — newest-first, for the audit API.
	ListByAgent(ctx context.Context, agentID uuid.UUID, limit int) ([]state.AgentState, error)
	// ListActiveByMatch — every non-terminal state on one match (the
	// match end sweep moves them to RETROSPECTIVE).
	ListActiveByMatch(ctx context.Context, matchID string) ([]state.AgentState, error)
}

// EvolutionRepository — the per-cluster draft narrative sequence.
type EvolutionRepository interface {
	Record(ctx context.Context, r evolution.Record) error
	// CountForCluster — how many drafts this agent already produced in
	// the cluster (drives sequence + the decision engine's
	// agent-history input).
	CountForCluster(ctx context.Context, agentID uuid.UUID, clusterID uuid.UUID) (int, error)
	// ListByCluster — the cluster's full narrative across agents
	// (narrative health reads draft-type composition).
	ListByCluster(ctx context.Context, clusterID uuid.UUID, limit int) ([]evolution.Record, error)
	List(ctx context.Context, limit int) ([]evolution.Record, error)
}

// DraftRepository — generated structured drafts.
type DraftRepository interface {
	Save(ctx context.Context, d draft.Draft) error
}

// PublicationCandidate — one queued draft awaiting the future
// publishing sprints.
type PublicationCandidate struct {
	DraftID  uuid.UUID
	AgentID  uuid.UUID
	TrendID  string
	Queue    string
	Priority bool
}

// PublicationRepository — the durable record of what entered which
// agent queue.
type PublicationRepository interface {
	RecordCandidate(ctx context.Context, c PublicationCandidate) error
}

// QueuedDraft — one unit of publishing work, self-contained.
//
// It carries the draft AND the context and decision that produced it, so
// the publish worker acts on exactly what the pipeline saw. Re-deriving the
// context inside the worker would read memories at a later instant, and the
// post would then be phrased from a story state the decision never
// evaluated.
type QueuedDraft struct {
	Draft    draft.Draft                  `json:"draft"`
	Context  draft.Context                `json:"context"`
	Decision decision.PublicationDecision `json:"decision"`
	Priority bool                         `json:"priority"`
}

// DraftQueue — the per-agent publishing queues
// (insight:queue:nexus:{agent}). Atlas never knows these exist.
//
// WRITE SIDE. Enqueue is called by the trend pipeline; Depth backs the
// "drafts waiting to publish" gauge.
type DraftQueue interface {
	Enqueue(ctx context.Context, queueName string, item QueuedDraft) error
	Depth(ctx context.Context, queueName string) (int64, error)
}

// QueuedDraftHandler processes one dequeued item. Returning an error leaves
// the entry unacknowledged so it is redelivered — the safe direction, since
// the publisher records product outcomes (suppressed / invalid / ticketed)
// as data rather than as errors.
type QueuedDraftHandler func(ctx context.Context, item QueuedDraft) error

// DraftQueueConsumer — the READ side of the publishing queues.
//
// This half did not exist. Enqueue wrote to a stream nothing ever read: the
// queue grew until MaxLen silently trimmed the oldest drafts, the "active
// jobs" gauge reported a number that could only rise, and publication really
// happened inline in the trend consumer — where one slow LLM call stalled
// every other agent and every later trend.
type DraftQueueConsumer interface {
	// Consume blocks until ctx is cancelled, dispatching entries from
	// every queue in queueNames.
	Consume(ctx context.Context, queueNames []string, handler QueuedDraftHandler) error
}

// ---- Sprint 4: publication engine ports ----

// PersonaRepository — persisted agent personas (admin-editable).
type PersonaRepository interface {
	Get(ctx context.Context, slug string) (persona.AgentPersona, error)
	List(ctx context.Context) ([]persona.AgentPersona, error)
	Upsert(ctx context.Context, p persona.AgentPersona) error
}

// CandidateRepository — every publication attempt, explainable.
type CandidateRepository interface {
	Save(ctx context.Context, c publication.Candidate) error
	List(ctx context.Context, status publication.CandidateStatus, limit int) ([]publication.Candidate, error)
	// History — newest-first PUBLISHED candidates (the publication
	// history API).
	History(ctx context.Context, limit int) ([]publication.Candidate, error)
	// AgentCounts — per-agent published/suppressed/ticketed counts
	// (the agent publication metrics API).
	AgentCounts(ctx context.Context) (map[string]map[string]int, error)
}

// TicketRepository — the human-review fallback queue.
type TicketRepository interface {
	Save(ctx context.Context, t publication.Ticket) error
	Get(ctx context.Context, id uuid.UUID) (publication.Ticket, error)
	List(ctx context.Context, status publication.TicketStatus, limit int) ([]publication.Ticket, error)
}

// AuditRepository — the immutable Console audit log (Sprint 4.5).
// Record + List only: audit events are never updated or deleted.
type AuditRepository interface {
	Record(ctx context.Context, e publication.AuditEvent) error
	List(ctx context.Context, filter AuditFilter) ([]publication.AuditEvent, error)
}

// TrendDLQ — V1.1 poison-message policy: dead-lettered trend entries
// are inspectable and replayable, never silently discarded.
type TrendDLQ interface {
	List(ctx context.Context, limit int64) ([]DLQEntry, error)
	Get(ctx context.Context, id string) (DLQEntry, error)
	Replay(ctx context.Context, id string) error
	Depth(ctx context.Context) (int64, error)
}

// DLQEntry — one dead-lettered stream entry.
type DLQEntry struct {
	ID            string `json:"id"`
	SourceEntryID string `json:"source_entry_id"`
	Kind          string `json:"kind"` // poison | max_deliveries
	Reason        string `json:"reason,omitempty"`
	Payload       string `json:"payload"` // JSON: {payload, error, reason|attempts, agent}
}

// AuditFilter — search surface for the audit center.
type AuditFilter struct {
	Actor      string
	Action     string
	EntityType string
	EntityID   string
	Limit      int
}

// SocialPublisher — the ONLY publication target. Implementations use
// Social's public APIs (gRPC PostService) — never Social storage.
type SocialPublisher interface {
	// PublishAgentPost creates the post as the agent
	// (author_type=agent, seeded Social author id). Returns the
	// Social post id.
	PublishAgentPost(ctx context.Context, req AgentPostRequest) (string, error)
}

// AgentPostRequest — the Social Foundation post shape (Part 9): no
// Social-side transformation needed.
type AgentPostRequest struct {
	SocialAuthorID uuid.UUID
	Content        string
	Metadata       map[string]string
	Visibility     string
}
