// Sprint B — Reaction application service.
//
// Thin wrapper: kind defaults applied at the domain layer
// (Kind.Resolve); validation lives at the gRPC handler boundary.
package reaction

import (
	"context"

	"github.com/google/uuid"

	domreaction "github.com/konoha-labs/insight-social/internal/domain/reaction"
)

type Service struct {
	repo domreaction.Repository
}

func New(repo domreaction.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) React(ctx context.Context, userID, discussionID uuid.UUID, kind domreaction.Kind) (*domreaction.Reaction, error) {
	return s.repo.React(ctx, userID, discussionID, kind.Resolve())
}

func (s *Service) Unreact(ctx context.Context, userID, discussionID uuid.UUID, kind domreaction.Kind) error {
	return s.repo.Unreact(ctx, userID, discussionID, kind.Resolve())
}

func (s *Service) StateForDiscussion(ctx context.Context, discussionID, viewerID uuid.UUID) (domreaction.DiscussionState, error) {
	return s.repo.StateForDiscussion(ctx, discussionID, viewerID)
}

func (s *Service) BatchStateForDiscussions(ctx context.Context, discussionIDs []uuid.UUID, viewerID uuid.UUID) ([]domreaction.DiscussionState, error) {
	if len(discussionIDs) == 0 {
		return nil, nil
	}
	return s.repo.BatchStateForDiscussions(ctx, discussionIDs, viewerID)
}
