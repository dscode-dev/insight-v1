// Package relationship is the application service for follow/block.
package relationship

import (
	"context"

	"github.com/google/uuid"

	domrelationship "github.com/konoha-labs/insight-social/internal/domain/relationship"
	"github.com/konoha-labs/insight-social/internal/observability"
)

const (
	defaultListLimit = 50
	maxListLimit     = 200
)

type Service struct {
	repo domrelationship.Repository
}

func New(repo domrelationship.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) Follow(ctx context.Context, actorID, targetID uuid.UUID) (*domrelationship.Relationship, error) {
	if actorID == targetID {
		return nil, domrelationship.ErrSelfTarget
	}
	rel, err := s.repo.Follow(ctx, actorID, targetID)
	if err != nil {
		return nil, err
	}
	observability.FollowsTotal.WithLabelValues("api").Inc()
	return rel, nil
}

// Mute flags an existing follow edge: the target stays followed but
// never appears in the actor's feeds (Sprint 3 product rule).
func (s *Service) Mute(ctx context.Context, actorID, targetID uuid.UUID) (*domrelationship.Relationship, error) {
	if actorID == targetID {
		return nil, domrelationship.ErrSelfTarget
	}
	rel, err := s.repo.Mute(ctx, actorID, targetID)
	if err != nil {
		return nil, err
	}
	observability.MutedRelationshipsTotal.WithLabelValues("mute").Inc()
	return rel, nil
}

func (s *Service) Unmute(ctx context.Context, actorID, targetID uuid.UUID) (*domrelationship.Relationship, error) {
	if actorID == targetID {
		return nil, domrelationship.ErrSelfTarget
	}
	rel, err := s.repo.Unmute(ctx, actorID, targetID)
	if err != nil {
		return nil, err
	}
	observability.MutedRelationshipsTotal.WithLabelValues("unmute").Inc()
	return rel, nil
}

func (s *Service) Unfollow(ctx context.Context, actorID, targetID uuid.UUID) error {
	if actorID == targetID {
		return domrelationship.ErrSelfTarget
	}
	return s.repo.Unfollow(ctx, actorID, targetID)
}

func (s *Service) Block(ctx context.Context, actorID, targetID uuid.UUID) (*domrelationship.Relationship, error) {
	if actorID == targetID {
		return nil, domrelationship.ErrSelfTarget
	}
	return s.repo.Block(ctx, actorID, targetID)
}

func (s *Service) ListFollowers(ctx context.Context, userID uuid.UUID, limit int, cursor string) (domrelationship.ListPage, error) {
	return s.repo.ListFollowers(ctx, domrelationship.ListFilter{
		UserID: userID, Limit: clampLimit(limit), Cursor: cursor,
	})
}

func (s *Service) ListFollowing(ctx context.Context, userID uuid.UUID, limit int, cursor string) (domrelationship.ListPage, error) {
	return s.repo.ListFollowing(ctx, domrelationship.ListFilter{
		UserID: userID, Limit: clampLimit(limit), Cursor: cursor,
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
