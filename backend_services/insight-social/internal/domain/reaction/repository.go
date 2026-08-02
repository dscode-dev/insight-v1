package reaction

import (
	"context"

	"github.com/google/uuid"
)

type Repository interface {
	// React inserts the (user, discussion, kind) tuple if absent.
	// Idempotent: a duplicate insert returns the existing row.
	React(ctx context.Context, userID, discussionID uuid.UUID, kind Kind) (*Reaction, error)

	// Unreact removes the tuple if present. Idempotent: a no-op when
	// the row doesn't exist (no error).
	Unreact(ctx context.Context, userID, discussionID uuid.UUID, kind Kind) error

	// StateForDiscussion returns the count + (optional) viewer flag
	// in one round-trip. When viewerID == uuid.Nil, LikedByUser stays
	// false.
	StateForDiscussion(ctx context.Context, discussionID uuid.UUID, viewerID uuid.UUID) (DiscussionState, error)

	// BatchStateForDiscussions: bulk variant for feed rendering.
	// Returns one DiscussionState per id in the input slice (empty
	// state — count=0 — for unknown ids; never a partial set).
	BatchStateForDiscussions(ctx context.Context, discussionIDs []uuid.UUID, viewerID uuid.UUID) ([]DiscussionState, error)
}
