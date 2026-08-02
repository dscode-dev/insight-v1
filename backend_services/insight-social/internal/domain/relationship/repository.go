package relationship

import (
	"context"

	"github.com/google/uuid"
)

type Repository interface {
	Follow(ctx context.Context, actorID, targetID uuid.UUID) (*Relationship, error)
	Unfollow(ctx context.Context, actorID, targetID uuid.UUID) error
	// Block creates the 'block' edge AND removes any 'follow' edge
	// in either direction, atomically. Returns the new 'block' row.
	Block(ctx context.Context, actorID, targetID uuid.UUID) (*Relationship, error)

	// Mute / Unmute toggle the muted flag on an EXISTING follow
	// edge (muted accounts remain followed). ErrNotFound when the
	// actor doesn't follow the target.
	Mute(ctx context.Context, actorID, targetID uuid.UUID) (*Relationship, error)
	Unmute(ctx context.Context, actorID, targetID uuid.UUID) (*Relationship, error)

	// FollowIdempotent creates the follow edge if absent and no-ops
	// when it already exists (used by automatic agent following).
	FollowIdempotent(ctx context.Context, actorID, targetID uuid.UUID) error

	// FollowingIDs returns the ids the user follows. When
	// excludeMuted is true, muted follows are omitted — the feed
	// path's view of the graph.
	FollowingIDs(ctx context.Context, userID uuid.UUID, excludeMuted bool) ([]uuid.UUID, error)

	// Followers: rows where target_id = userID AND kind = 'follow'.
	ListFollowers(ctx context.Context, f ListFilter) (ListPage, error)
	// Following: rows where actor_id = userID AND kind = 'follow'.
	ListFollowing(ctx context.Context, f ListFilter) (ListPage, error)
}
