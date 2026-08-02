// Package reputationrepo is the pgx-backed Reputation repository.
//
// Cross-aggregate write: this package writes to `users.reputation` +
// `users.tier`, which are columns logically owned by the User
// aggregate but denormalised here as a read cache of the
// reputation_events ledger. That coupling is acceptable because:
//   - The User aggregate never *mutates* reputation — it only reads
//     it (UserService.Stats / Get).
//   - Recompute is the ONLY writer; there's no race with user-driven
//     mutations on these columns.
//   - The legacy service used the same denormalisation pattern; preserving it
//     keeps the gateway Strangler simple (no behavior diff).
package reputationrepo

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	domreputation "github.com/konoha-labs/insight-social/internal/domain/reputation"
	domuser "github.com/konoha-labs/insight-social/internal/domain/user"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

// Get: read the cache + derive accuracy from signals/reputation_events.
//
// Accuracy uses the same numerator/denominator UserStats does, kept
// consistent so /users/{id}/stats.accuracy == /reputation/{id}.accuracy.
const getSQL = `
SELECT
    u.id,
    u.reputation,
    u.tier,
    (SELECT COUNT(*) FROM signals          WHERE author_id = u.id)                                AS signals_sent,
    (SELECT COUNT(*) FROM reputation_events WHERE user_id  = u.id AND kind = 'signal_validated')  AS signals_validated
  FROM users u
 WHERE u.id = $1
`

func (r *Repository) Get(ctx context.Context, userID uuid.UUID) (domreputation.Reputation, error) {
	var (
		id               uuid.UUID
		score            int
		tierStr          string
		signalsSent      int64
		signalsValidated int64
	)
	err := r.pool.QueryRow(ctx, getSQL, userID).Scan(
		&id, &score, &tierStr, &signalsSent, &signalsValidated,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return domreputation.Reputation{}, domreputation.ErrUserNotFound
		}
		return domreputation.Reputation{}, fmt.Errorf("reputationrepo get: %w", err)
	}
	var accuracy float64
	if signalsSent > 0 {
		accuracy = float64(signalsValidated) / float64(signalsSent)
	}
	return domreputation.Reputation{
		UserID:   id,
		Score:    domreputation.ClampScore(score),
		Tier:     domuser.ParseTier(tierStr),
		Accuracy: accuracy,
	}, nil
}

// Recompute: SUM the ledger, clamp, write back, return projection.
// Single CTE so we never have a moment where the cache is half-
// written. GREATEST/LEAST clamp inside SQL — keeps the bounds in
// one place (matches domain.ClampScore exactly).
//
// Tier is computed by switching on the clamped score range — same
// boundaries as domain/user.TierForScore (we can't call Go code
// from SQL, so the boundaries are duplicated here. If they ever
// change, both sites need updating; the unit test would catch drift).
const recomputeSQL = `
WITH ledger AS (
    SELECT COALESCE(SUM(delta), 0)::int AS raw_score
      FROM reputation_events
     WHERE user_id = $1
), clamped AS (
    SELECT LEAST(100, GREATEST(0, raw_score)) AS score FROM ledger
), updated AS (
    UPDATE users
       SET reputation = clamped.score,
           tier = CASE
                    WHEN clamped.score < 40 THEN 'rookie'
                    WHEN clamped.score < 60 THEN 'scout'
                    WHEN clamped.score < 85 THEN 'analyst'
                    ELSE 'oracle'
                  END
      FROM clamped
     WHERE users.id = $1
    RETURNING users.id, users.reputation, users.tier
)
SELECT
    u.id, u.reputation, u.tier,
    (SELECT COUNT(*) FROM signals          WHERE author_id = u.id)                                AS signals_sent,
    (SELECT COUNT(*) FROM reputation_events WHERE user_id  = u.id AND kind = 'signal_validated')  AS signals_validated
  FROM updated u
`

func (r *Repository) Recompute(ctx context.Context, userID uuid.UUID) (domreputation.Reputation, error) {
	var (
		id               uuid.UUID
		score            int
		tierStr          string
		signalsSent      int64
		signalsValidated int64
	)
	err := r.pool.QueryRow(ctx, recomputeSQL, userID).Scan(
		&id, &score, &tierStr, &signalsSent, &signalsValidated,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// No users row matched: the user doesn't exist.
			return domreputation.Reputation{}, domreputation.ErrUserNotFound
		}
		return domreputation.Reputation{}, fmt.Errorf("reputationrepo recompute: %w", err)
	}
	var accuracy float64
	if signalsSent > 0 {
		accuracy = float64(signalsValidated) / float64(signalsSent)
	}
	return domreputation.Reputation{
		UserID:   id,
		Score:    domreputation.ClampScore(score),
		Tier:     domuser.ParseTier(tierStr),
		Accuracy: accuracy,
	}, nil
}
