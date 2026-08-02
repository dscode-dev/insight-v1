package user

import (
	"context"

	"github.com/google/uuid"
)

// Repository is the port. The aggregate doesn't know whether it's
// persisted by pgx, Memory, or anything else — only that one of these
// methods will be called.
//
// Stats is a separate read-model query and would normally live behind
// its own port (CQRS-style). Inlining it here keeps the W2.1a surface
// small; promote to a dedicated `StatsReader` interface if/when more
// read models accumulate.
type Repository interface {
	Insert(ctx context.Context, u *User) error
	GetByID(ctx context.Context, id uuid.UUID) (*User, error)
	GetByUsername(ctx context.Context, username string) (*User, error)
	List(ctx context.Context, ids []uuid.UUID) ([]*User, error)
	UpdateAccent(ctx context.Context, id uuid.UUID, accentColor string) (*User, error)
	// UpdateAvatar — Sprint C. Empty avatarURL clears the column to NULL.
	UpdateAvatar(ctx context.Context, id uuid.UUID, avatarURL string) (*User, error)
	Stats(ctx context.Context, id uuid.UUID) (Stats, error)
}

// Stats is the read model returned by Repository.Stats — denormalised
// counts pulled from signals / community_members / reputation_events.
// Lives here (not in application) so the repo can build + return it
// without crossing layers.
type Stats struct {
	UserID            uuid.UUID
	SignalsSent       int64
	SignalsValidated  int64
	SignalsFlagged    int64
	MatchesFollowed   int64
	CommunitiesJoined int64
	Accuracy          float64 // 0..1; 0 when SignalsSent == 0
}
