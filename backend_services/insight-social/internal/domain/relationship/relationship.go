// Package relationship holds the Relationship value type (graph edge
// between two users) + the read-side ListPage shape.
//
// Schema invariants enforced at the DB layer:
//   - CHECK (actor_id <> target_id)         — no self-edges
//   - UNIQUE (actor_id, target_id, kind)    — at most one of each kind
//
// Blocking semantics (W2.1b minimum):
//
//	When Block(source, target) is invoked, ANY existing 'follow'
//	edge in either direction is removed atomically. This matches
//	the legacy schema and Twitter-style block behaviour. See repo.Block.
package relationship

import (
	"time"

	"github.com/google/uuid"
)

type Relationship struct {
	ActorID   uuid.UUID
	TargetID  uuid.UUID
	Kind      Kind
	CreatedAt time.Time
	// Mute (Sprint 3): muted accounts remain followed but their
	// posts never appear in the actor's feeds.
	Muted   bool
	MutedAt *time.Time
}

type ListFilter struct {
	UserID uuid.UUID
	Limit  int
	Cursor string
}

type ListPage struct {
	Relationships []*Relationship
	NextCursor    string
}
