// Package community is the application service for the Community
// aggregate.
//
// Use cases:
//   - List           (paged, optional kind filter)
//   - Get            (by id)
//   - CreateTopic    (user-curated; competition communities sync from
//     a different path not yet implemented)
//   - Join / Leave   (membership mutations)
package community

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	domcommunity "github.com/konoha-labs/insight-social/internal/domain/community"
)

const (
	defaultListLimit = 20
	maxListLimit     = 100
)

type Service struct {
	repo domcommunity.Repository
}

func New(repo domcommunity.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) List(ctx context.Context, kind *domcommunity.Kind, sort domcommunity.Sort, limit int, cursor string) (domcommunity.ListPage, error) {
	return s.repo.List(ctx, domcommunity.ListFilter{
		Kind:   kind,
		Sort:   sort.Resolve(),
		Limit:  clampLimit(limit),
		Cursor: cursor,
	})
}

// ListForUser backs the gateway Hub "mine" segment. Returns the
// caller's joined communities, most-recent membership first.
func (s *Service) ListForUser(ctx context.Context, userID uuid.UUID, limit int, cursor string) (domcommunity.ListPage, error) {
	return s.repo.ListForUser(ctx, domcommunity.ListForUserFilter{
		UserID: userID,
		Limit:  clampLimit(limit),
		Cursor: cursor,
	})
}

func clampLimit(limit int) int {
	if limit <= 0 {
		return defaultListLimit
	}
	if limit > maxListLimit {
		return maxListLimit
	}
	return limit
}

func (s *Service) Get(ctx context.Context, id uuid.UUID) (*domcommunity.Community, error) {
	return s.repo.GetByID(ctx, id)
}

// CreateTopic creates a user-owned topic community. ownerUserID is derived by
// the caller (gateway) from the trusted session, never from client data. The
// community and its OWNER membership are persisted atomically (InsertOwned), so
// a new community is never born without an owner.
func (s *Service) CreateTopic(ctx context.Context, slug, name, topic, accentColor string, ownerUserID uuid.UUID) (*domcommunity.Community, error) {
	c, err := domcommunity.NewTopic(slug, name, topic, accentColor, ownerUserID)
	if err != nil {
		return nil, err
	}
	if _, err := s.repo.InsertOwned(ctx, c); err != nil {
		return nil, fmt.Errorf("insert owned community: %w", err)
	}
	return c, nil
}

// ListMembers returns enriched, keyset-paginated members. roleFilter is
// optional (nil = all roles); owner/admin/moderator projections reuse this.
func (s *Service) ListMembers(ctx context.Context, communityID uuid.UUID, roleFilter *domcommunity.Role, limit int, cursor string) (domcommunity.MembersPage, error) {
	return s.repo.ListMembers(ctx, domcommunity.ListMembersFilter{
		CommunityID: communityID,
		Limit:       clampLimit(limit),
		Cursor:      cursor,
		RoleFilter:  roleFilter,
	})
}

// GetMembership resolves the viewer's membership (role) or ErrNotMember.
func (s *Service) GetMembership(ctx context.Context, communityID, userID uuid.UUID) (*domcommunity.Membership, error) {
	return s.repo.GetMembership(ctx, communityID, userID)
}

// GetStats returns the user-independent numeric projection for a community.
func (s *Service) GetStats(ctx context.Context, communityID uuid.UUID) (domcommunity.Stats, error) {
	return s.repo.GetStats(ctx, communityID)
}

func (s *Service) Join(ctx context.Context, communityID, userID uuid.UUID) (*domcommunity.Membership, error) {
	return s.repo.AddMember(ctx, communityID, userID)
}

func (s *Service) Leave(ctx context.Context, communityID, userID uuid.UUID) error {
	// The owner-leave invariant is enforced atomically in the repository
	// (RemoveMember refuses an owner row → ErrOwnerCannotLeave). Kept there
	// rather than here so no write path can bypass it.
	return s.repo.RemoveMember(ctx, communityID, userID)
}
