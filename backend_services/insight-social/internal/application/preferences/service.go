// Package preferences is the application service for user settings.
//
// Thin: validation in the domain Update.Validate; repo handles upsert
// semantics. No cross-aggregate concerns (preferences are owned by
// the User bounded context but live in their own table for normal
// 1:1 storage hygiene).
package preferences

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	dompreferences "github.com/konoha-labs/insight-social/internal/domain/preferences"
)

type Service struct {
	repo dompreferences.Repository
}

func New(repo dompreferences.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) Get(ctx context.Context, userID uuid.UUID) (dompreferences.Preferences, error) {
	return s.repo.Get(ctx, userID)
}

func (s *Service) Update(ctx context.Context, userID uuid.UUID, patch dompreferences.Update) (dompreferences.Preferences, error) {
	if err := patch.Validate(); err != nil {
		return dompreferences.Preferences{}, err
	}
	out, err := s.repo.Update(ctx, userID, patch)
	if err != nil {
		return dompreferences.Preferences{}, fmt.Errorf("update preferences: %w", err)
	}
	return out, nil
}
