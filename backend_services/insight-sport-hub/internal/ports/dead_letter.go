// DeadLetterStore — Sprint 4 contract.
//
// The port the queue adapter calls when a SyncJob terminally fails.
// Sprint 4 ships a NOOP implementation (Record() is a no-op + log).
// Sprint 5+ will land a Postgres-backed store + admin endpoints for
// inspection / replay.
//
// Architectural rule: the queue adapter NEVER stores failures
// itself — it always routes through this port so the storage
// concern stays swappable.
package ports

import (
	"context"
	"time"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

// DeadLetterStore — the port. Implementations must be safe to call
// concurrently from many workers.
type DeadLetterStore interface {
	// Record persists the failure. Returning an error is informational
	// — the queue adapter logs but does NOT block the consumer loop on
	// DLQ storage failures.
	Record(ctx context.Context, failure syncdom.SyncJobFailure) error
}

// DeadLetterRecord — Sprint 5.1 read model returned by the inspect
// + replay endpoints. Carries the row's primary id + the replay
// state distinct from the recorded SyncJobFailure. Implementations
// may store extra rows (e.g. audit log of replays); the read path
// returns the latest state.
type DeadLetterRecord struct {
	ID         string
	Failure    syncdom.SyncJobFailure
	ReplayedAt *time.Time
	CreatedAt  time.Time
}

// DeadLetterQuery is the filter shape for List. Zero values disable
// the corresponding filter — empty Provider matches all providers,
// zero Limit defaults to a sensible page size at the adapter.
type DeadLetterQuery struct {
	Provider    string // exact match on provider_id slug
	FailureType string // string slug; "" matches all
	Unreplayed  bool   // true → only rows with replayed_at IS NULL
	Limit       int    // 0 → adapter default
	Offset      int
}

// DeadLetterReader — separated from DeadLetterStore so the queue
// adapter only needs the Record half (small surface) while the HTTP
// handler gets List/Get/MarkReplayed. Implementations may satisfy
// both interfaces with one struct.
type DeadLetterReader interface {
	List(ctx context.Context, q DeadLetterQuery) ([]DeadLetterRecord, error)
	Get(ctx context.Context, id string) (DeadLetterRecord, error)
	MarkReplayed(ctx context.Context, id string, at time.Time) error
}
