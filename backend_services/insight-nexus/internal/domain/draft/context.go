package draft

import (
	"github.com/google/uuid"

	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
)

// Context is the complete input to the draft generator: what one agent
// knows when drafting about one story.
//
// WHY IT LIVES IN THE DOMAIN. It used to be `contextbuilder.DraftContext`,
// in the application layer. Publication became asynchronous, which means the
// publishing queue has to carry this across a process boundary — and the
// queue contract lives in `ports`, which is forbidden from importing
// application code. Rebuilding it inside the worker was the alternative, and
// it would have re-read memories at a different instant than the decision
// was made, so the post would be phrased from a context the decision never
// saw.
//
// It qualifies as domain on its own terms: pure data, no behaviour, no
// dependency outside other domain packages.
type Context struct {
	Agent agent.Agent `json:"agent"`
	Trend trend.Event `json:"trend"`
	// StreamPriority — Atlas's priority flag on the consumed stream
	// entry (transport-level). The communication priority band lives
	// in Priority below (decision-driven).
	StreamPriority bool `json:"stream_priority"`

	// Memories — newest-first match-scoped continuity (≤ MemoryWindow).
	Memories []memory.Memory `json:"memories,omitempty"`
	// Related — newest-first story-cluster continuity across matches
	// (≤ MemoryWindow). Lets Oracle-style narratives reference
	// previous encounters.
	Related   []memory.Memory `json:"related,omitempty"`
	MemoryHit bool            `json:"memory_hit"`

	// ---- Sprint 3: communication-intelligence context (set by the
	// pipeline after the decision/state/evolution engines ran).
	ClusterID   uuid.UUID `json:"cluster_id"`
	ClusterType string    `json:"cluster_type"`
	Action      string    `json:"action"`
	// Priority — the decision engine's priority band
	// (LOW/MEDIUM/HIGH/CRITICAL). Renamed from the temporary
	// Priority2 in Sprint 3.5; the wire metadata key ("priority") is
	// unchanged.
	Priority   string `json:"priority"`
	AgentState string `json:"agent_state"`
	DraftType  string `json:"draft_type"`
	Sequence   int    `json:"sequence"`
}
