// Package reputation is the application service for Reputation RPCs.
//
// Thin pass-through: validation + clamping live in the domain layer
// (ClampScore) and the repo (Recompute does the SUM + UPDATE in one
// CTE). The service exists so the gRPC handler doesn't depend on
// the repo type directly.
package reputation

import (
	"context"

	"github.com/google/uuid"

	domreputation "github.com/konoha-labs/insight-social/internal/domain/reputation"
)

type Service struct {
	repo domreputation.Repository
}

func New(repo domreputation.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) Get(ctx context.Context, userID uuid.UUID) (domreputation.Reputation, error) {
	return s.repo.Get(ctx, userID)
}

func (s *Service) Recompute(ctx context.Context, userID uuid.UUID) (domreputation.Reputation, error) {
	return s.repo.Recompute(ctx, userID)
}
