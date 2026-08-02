// Package agent is the application service for AgentProfile reads.
// Agents are migration-seeded; this service only exposes them.
package agent

import (
	"context"

	"github.com/google/uuid"

	domagent "github.com/konoha-labs/insight-social/internal/domain/agent"
)

type Service struct {
	repo domagent.Repository
}

func New(repo domagent.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) List(ctx context.Context, activeOnly bool) ([]*domagent.Profile, error) {
	return s.repo.List(ctx, activeOnly)
}

func (s *Service) Get(ctx context.Context, id uuid.UUID) (*domagent.Profile, error) {
	return s.repo.GetByID(ctx, id)
}

func (s *Service) GetBySlug(ctx context.Context, slug string) (*domagent.Profile, error) {
	return s.repo.GetBySlug(ctx, slug)
}

// ActiveIDs returns the active agents' ids — the auto-follow target
// set and the feed's agent classifier.
func (s *Service) ActiveIDs(ctx context.Context) ([]uuid.UUID, error) {
	agents, err := s.repo.List(ctx, true)
	if err != nil {
		return nil, err
	}
	ids := make([]uuid.UUID, 0, len(agents))
	for _, a := range agents {
		ids = append(ids, a.ID)
	}
	return ids, nil
}
