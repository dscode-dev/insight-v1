// Package signal is the application service for the Signal aggregate.
//
// Create order is DB-first, publish-second:
//  1. domain.New (validate)
//  2. repo.Insert (assigns bigint id via RETURNING)
//  3. publisher.Publish (fan-out to Redis Stream)
//
// If step 3 fails after step 2, the row exists but no event went out.
// We return the publish error so the gateway can decide (retry,
// surface to user, etc.). Consumers idempotently dedupe on signal_id
// via SET-NX (see insight-gateway broker), so a retried Create is
// safe.
package signal

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-runtime-go/pkg/logging"
	domsignal "github.com/konoha-labs/insight-social/internal/domain/signal"
)

const (
	defaultListLimit = 50
	maxListLimit     = 200
)

type Service struct {
	repo      domsignal.Repository
	publisher domsignal.Publisher
}

func New(repo domsignal.Repository, publisher domsignal.Publisher) *Service {
	return &Service{repo: repo, publisher: publisher}
}

func (s *Service) Create(ctx context.Context, authorID, matchID uuid.UUID,
	source domsignal.Source, label, body string, confidence float64) (*domsignal.Signal, error) {

	sig, err := domsignal.New(authorID, matchID, source, label, body, confidence)
	if err != nil {
		return nil, err
	}
	if err := s.repo.Insert(ctx, sig); err != nil {
		return nil, fmt.Errorf("insert signal: %w", err)
	}

	if err := s.publisher.Publish(ctx, sig); err != nil {
		// Log + return wrapped error — operator should investigate.
		// Row is persisted; replaying via a Stream backfill recovers
		// the missing event.
		logger := logging.FromContext(ctx)
		logger.Error().
			Err(err).
			Int64("signal_id", sig.ID()).
			Str("match_id", sig.MatchID().String()).
			Msg("signal_publish_failed")
		return nil, errors.Join(domsignal.ErrPublish, err)
	}
	return sig, nil
}

func (s *Service) ListForMatch(ctx context.Context, matchID uuid.UUID, limit int, cursor string) (domsignal.ListPage, error) {
	return s.repo.ListForMatch(ctx, domsignal.ListForMatchFilter{
		MatchID: matchID, Limit: clampLimit(limit), Cursor: cursor,
	})
}

func (s *Service) ListForUser(ctx context.Context, userID uuid.UUID, limit int, cursor string) (domsignal.ListPage, error) {
	return s.repo.ListForUser(ctx, domsignal.ListForUserFilter{
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
