// NoopDLQ — Sprint 4 default DeadLetterStore.
//
// Sprint 4 ships the DLQ contract (ports.DeadLetterStore +
// syncdom.SyncJobFailure) and a NOOP implementation. Sprint 5+ will
// land a Postgres-backed store + admin endpoints; until then the
// queue adapter still calls into the port — when a Postgres impl
// drops in, no upstream code changes.
package queue

import (
	"context"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

// NoopDLQ implements ports.DeadLetterStore with no-op storage.
// Record returns nil unconditionally. Use only as a default — real
// deployments should wire a persistent store.
type NoopDLQ struct{}

// Record — no-op. Returning nil keeps the queue adapter from
// surfacing "failure recorded" log spam at debug levels.
func (NoopDLQ) Record(_ context.Context, _ syncdom.SyncJobFailure) error { return nil }
