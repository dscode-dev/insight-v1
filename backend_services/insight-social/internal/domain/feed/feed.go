// Package feed holds the read-model types for query-time feed
// generation — Sprint 3 (Social Foundation). No fanout-on-write, no
// materialized timelines: every read assembles the feed from the
// posts + relationships tables.
package feed

import (
	"context"
	"time"

	"github.com/google/uuid"

	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
)

// Item is one feed entry with denormalized author display data.
type Item struct {
	Post              *dompost.Post
	AuthorName        string
	AuthorAvatar      string
	FromFollowedAgent bool
	Sponsored         bool // future sponsored slots — always false in V1
	// LikedByMe is true when the requesting viewer has liked this post.
	// Set by the feed service (batch query) before returning.
	LikedByMe bool
}

type Page struct {
	Items      []*Item
	NextCursor string
}

// CandidateQuery scopes one candidate fetch.
type CandidateQuery struct {
	AuthorIDs []uuid.UUID
	Before    time.Time
	Limit     int
}

// Repository is the read port the feed service composes over. The
// implementation joins users / agent_profiles for display data.
type Repository interface {
	// PostsByAuthors returns non-deleted posts authored by any of the
	// given ids (public + competition visibility), newest first.
	PostsByAuthors(ctx context.Context, q CandidateQuery) ([]*Item, error)
	// RecentPublic returns non-deleted PUBLIC posts from any author,
	// newest first — the "relevant public posts" section.
	RecentPublic(ctx context.Context, before time.Time, limit int) ([]*Item, error)
	// LikedPostIDs returns, of the given post ids, the subset the
	// viewer has liked — used to populate Item.LikedByMe in one query.
	LikedPostIDs(ctx context.Context, viewerID uuid.UUID, postIDs []uuid.UUID) (map[uuid.UUID]bool, error)
}
