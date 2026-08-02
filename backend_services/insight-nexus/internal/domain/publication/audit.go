package publication

import (
	"time"

	"github.com/google/uuid"
)

// AuditEvent — one immutable operational audit record (Sprint 4.5).
// Every Console action is attributable: actor + action + before/after
// + reason. No silent modifications.
type AuditEvent struct {
	ID         uuid.UUID      `json:"id"`
	Actor      string         `json:"actor"`
	Action     string         `json:"action"`
	EntityType string         `json:"entity_type"`
	EntityID   string         `json:"entity_id"`
	Before     map[string]any `json:"before"`
	After      map[string]any `json:"after"`
	Reason     string         `json:"reason"`
	CreatedAt  time.Time      `json:"created_at"`
}
