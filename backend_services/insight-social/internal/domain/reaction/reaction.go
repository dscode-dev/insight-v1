// Package reaction holds the Reaction aggregate (Sprint B).
//
// Scope: Discussion reactions only. Target polymorphism deferred —
// see migrations/00002_reactions.sql for rationale.
//
// State machine:
//   - React(user, discussion, LIKE) → row exists; returns the row.
//     Idempotent: re-reacting returns the SAME row, not an error.
//   - Unreact(user, discussion, LIKE) → row removed if present.
//     Idempotent: unreacting twice is a no-op.
//
// The aggregate is a value type — no identity beyond the
// (user_id, discussion_id, kind) tuple. The repo handles the DB
// surrogate id internally.
package reaction

import (
	"time"

	"github.com/google/uuid"
)

type Reaction struct {
	UserID       uuid.UUID
	DiscussionID uuid.UUID
	Kind         Kind
	CreatedAt    time.Time
}

// DiscussionState is the read-model returned by StateForDiscussion.
// Optimised for the BFF rendering use case: one round-trip per
// discussion (or N in one bulk call) carries everything the heart
// button needs.
type DiscussionState struct {
	DiscussionID uuid.UUID
	LikeCount    int64
	LikedByUser  bool // false when no viewer specified
}
