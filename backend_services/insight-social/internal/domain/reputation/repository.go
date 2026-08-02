package reputation

import (
	"context"

	"github.com/google/uuid"
)

type Repository interface {
	// Get reads the cached reputation projection (users.reputation +
	// tier) plus accuracy derived from signals/reputation_events.
	// Returns ErrUserNotFound if no user row exists.
	Get(ctx context.Context, userID uuid.UUID) (Reputation, error)

	// Recompute rebuilds the cache from the ledger
	// (reputation_events.delta SUM) and writes it back to
	// users.reputation + users.tier. Returns the resulting
	// projection. Atomic via a single CTE — see repo impl.
	Recompute(ctx context.Context, userID uuid.UUID) (Reputation, error)
}
