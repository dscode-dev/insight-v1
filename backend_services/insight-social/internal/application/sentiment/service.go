// Package sentiment is the application service for the SentimentService.
//
// Read-only — there's no Create/Update RPC. The rollup that produces
// snapshots lives outside this service (Atlas intelligence).
package sentiment

import (
	"context"
	"time"

	"github.com/google/uuid"

	domsentiment "github.com/konoha-labs/insight-social/internal/domain/sentiment"
)

const (
	defaultHistoryWindow = 1 * time.Hour
	defaultMaxPoints     = 60
	maxAllowedPoints     = 240
)

type Service struct {
	repo domsentiment.Repository
}

func New(repo domsentiment.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) GetForMatch(ctx context.Context, matchID uuid.UUID) (domsentiment.Snapshot, error) {
	return s.repo.Latest(ctx, matchID)
}

func (s *Service) HistoryForMatch(ctx context.Context, matchID uuid.UUID, from time.Time, maxPoints int) ([]domsentiment.Point, error) {
	if from.IsZero() {
		from = time.Now().UTC().Add(-defaultHistoryWindow)
	}
	if maxPoints <= 0 {
		maxPoints = defaultMaxPoints
	}
	if maxPoints > maxAllowedPoints {
		maxPoints = maxAllowedPoints
	}
	return s.repo.History(ctx, domsentiment.HistoryFilter{
		MatchID:   matchID,
		From:      from,
		MaxPoints: maxPoints,
	})
}
