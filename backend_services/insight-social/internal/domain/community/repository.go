package community

import (
	"context"

	"github.com/google/uuid"
)

// ListFilter narrows a List query. All fields optional; Limit clamped
// to a sensible default at the repo (20 by default, 100 max).
type ListFilter struct {
	Kind  *Kind
	Limit int
	// Cursor encodes the keyset of the last item from the prior page.
	// Opaque at the application + interface layers; only meaningful
	// when Sort.Resolve() == SortNewest in W2.2.1 (HOT/POPULAR don't
	// support multi-page pagination yet — see repo comments).
	Cursor string
	Sort   Sort
}

// ListForUserFilter scopes List to communities a user is a member of.
// Order: most-recently-joined first (cm.joined_at DESC, c.id DESC).
type ListForUserFilter struct {
	UserID uuid.UUID
	Limit  int
	Cursor string // encodes (joined_at, community_id) — separate codec from ListFilter
}

// ListMembersFilter scopes a keyset members listing to one community, ordered
// by (role priority ASC, joined_at ASC, user_id ASC). RoleFilter optionally
// projects a single tier (e.g. only admins) from the SAME query — there is no
// separate owner/admin/moderator listing.
type ListMembersFilter struct {
	CommunityID uuid.UUID
	Limit       int
	Cursor      string
	RoleFilter  *Role // nil = all roles
}

// ListPage is the repo's return shape — denormalised so the
// application layer can pass it straight back to the handler.
type ListPage struct {
	Communities []*Community
	NextCursor  string // empty when no more pages
}

type Repository interface {
	// Insert persists an OWNERLESS community (competition/auto-created path;
	// stays OWNER_UNASSIGNED). Topic communities created by a user use
	// InsertOwned instead.
	Insert(ctx context.Context, c *Community) error
	// InsertOwned persists a community AND its OWNER membership atomically in
	// one transaction, and sets communities.owner_user_id — the three writes
	// that keep owner_user_id in sync with exactly one OWNER row. c must have
	// OwnerAssigned() == true.
	InsertOwned(ctx context.Context, c *Community) (*Membership, error)
	GetByID(ctx context.Context, id uuid.UUID) (*Community, error)
	GetBySlug(ctx context.Context, slug string) (*Community, error)
	List(ctx context.Context, f ListFilter) (ListPage, error)
	// ListForUser returns the communities the user is currently a
	// member of, ordered by recency of join. Added in W2.2.1 to back
	// the gateway Hub "mine" segment.
	ListForUser(ctx context.Context, f ListForUserFilter) (ListPage, error)
	// ListMembers returns enriched, keyset-paginated members (JOIN users, no
	// N+1) ordered by role priority then joined_at then user_id.
	ListMembers(ctx context.Context, f ListMembersFilter) (MembersPage, error)
	// GetMembership resolves ONE user's membership (role) in a community, or
	// ErrNotMember. Backs the aggregate's viewer_role / membership_status.
	GetMembership(ctx context.Context, communityID, userID uuid.UUID) (*Membership, error)
	// GetStats returns the user-independent numeric projection (member/active/
	// discussion counts + role distribution). ErrNotFound if the community
	// does not exist.
	GetStats(ctx context.Context, communityID uuid.UUID) (Stats, error)

	// Membership writes:
	AddMember(ctx context.Context, communityID, userID uuid.UUID) (*Membership, error)
	// RemoveMember deletes a NON-owner membership. It is idempotent for a
	// non-member (ErrNotMember) and refuses to remove the OWNER
	// (ErrOwnerCannotLeave) — the owner-leave invariant is enforced in the
	// same statement so no generic delete can orphan a community.
	RemoveMember(ctx context.Context, communityID, userID uuid.UUID) error
}
