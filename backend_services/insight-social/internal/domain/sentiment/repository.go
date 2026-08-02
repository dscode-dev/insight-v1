package sentiment

import (
	"context"
	"time"

	"github.com/google/uuid"
)

type HistoryFilter struct {
	MatchID   uuid.UUID
	From      time.Time // zero = default lower bound (handled by repo)
	MaxPoints int       // 0 = repo default (60)
}

type Repository interface {
	// Latest snapshot for a match. Returns ErrNotFound if no row.
	Latest(ctx context.Context, matchID uuid.UUID) (Snapshot, error)

	// History returns ordered Points (ASC by captured_at), already
	// downsampled to <= MaxPoints. Empty slice + nil error when no
	// snapshots in range.
	History(ctx context.Context, f HistoryFilter) ([]Point, error)
}
