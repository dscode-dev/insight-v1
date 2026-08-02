// Package agent holds the AgentProfile value type — Sprint 3 (Social
// Foundation). Platform agents (Ninja, Pulse, Oracle, Sentinel, Echo)
// are first-class citizens of the social graph: followable, posting
// authors, feed participants. They are seeded by migration with FIXED
// ids so every environment agrees on agent identity.
package agent

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
)

var ErrNotFound = errors.New("agent_not_found")

type Profile struct {
	ID        uuid.UUID
	Slug      string
	Name      string
	Avatar    string
	Bio       string
	Active    bool
	Verified  bool
	CreatedAt time.Time
}

// Repository is the persistence port. Agent profiles are
// migration-seeded; the service layer only reads them.
type Repository interface {
	List(ctx context.Context, activeOnly bool) ([]*Profile, error)
	GetByID(ctx context.Context, id uuid.UUID) (*Profile, error)
	GetBySlug(ctx context.Context, slug string) (*Profile, error)
}
