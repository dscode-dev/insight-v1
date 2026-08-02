package signal

import (
	"context"

	"github.com/google/uuid"
)

type ListForMatchFilter struct {
	MatchID uuid.UUID
	Limit   int
	Cursor  string
}

type ListForUserFilter struct {
	UserID uuid.UUID
	Limit  int
	Cursor string
}

type ListPage struct {
	Signals    []*Signal
	NextCursor string
}

type Repository interface {
	// Insert assigns the BIGSERIAL id back onto the aggregate via
	// SetID, then returns. Caller MUST pass a Signal whose id == 0.
	Insert(ctx context.Context, s *Signal) error
	GetByID(ctx context.Context, id int64) (*Signal, error)
	ListForMatch(ctx context.Context, f ListForMatchFilter) (ListPage, error)
	ListForUser(ctx context.Context, f ListForUserFilter) (ListPage, error)
}

// Publisher is the port for fan-out (Redis Streams in the prod impl).
// The application service calls Publish AFTER the repo insert
// succeeds so the stream entry always references a persisted row —
// consumers can safely look it up by id.
type Publisher interface {
	Publish(ctx context.Context, s *Signal) error
}
