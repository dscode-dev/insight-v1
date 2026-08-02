// JobQueue — Sprint 3 contract, extended in Sprint 4.
//
// The contract between the Scheduler (producer) and the JobRunner
// (consumer). Sprint 4 swaps the backing implementation from the
// in-memory channel to Redis Streams while preserving every
// guarantee from Sprint 3:
//
//   - FIFO ordering (Redis: stream insertion order)
//   - bounded capacity (Redis: XADD with MAXLEN ~ cap)
//   - non-blocking Enqueue (Redis: at-capacity yields ErrQueueFull)
//   - blocking Dequeue with ctx cancel (Redis: XREADGROUP BLOCK + ctx)
//   - graceful Close (Redis: drains pending acks, stops new reads)
//
// Sprint 4 additions:
//   - `Delivery` carries an opaque AckToken so the consumer can
//     acknowledge / retry / fail per-message without leaking
//     transport details.
//   - Ack / Retry / Fail give the runner control over the message
//     lifecycle. Retry re-enqueues with bumped CurrentAttempt and a
//     `RetryAfter` honoured by the queue. Fail records a terminal
//     failure via the DeadLetterStore (Sprint 4 contract, no-op
//     storage; Sprint 5+ persists).
//
// Critical architectural rule (Sprint 4): NO application package may
// import the Redis client. Only the queue adapter does. Boundary
// tests parse the import graph + fail on any leak.
package ports

import (
	"context"
	"errors"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

// ErrQueueFull — Enqueue rejected because capacity is exhausted.
var ErrQueueFull = errors.New("queue: capacity exceeded")

// ErrQueueClosed — the queue has been shut down. Producers and
// consumers receive this after Close.
var ErrQueueClosed = errors.New("queue: closed")

// Delivery is what Dequeue hands back. The Job is the work payload;
// AckToken is opaque (in-memory: the in-process delivery id; Redis:
// the stream message ID). Attempt is the **current** attempt number
// (1-indexed) — the runner uses this to detect "attempts exhausted"
// before invoking the adapter.
type Delivery struct {
	Job      syncdom.SyncJob
	Attempt  int
	AckToken string
}

// JobQueue is the FIFO-style transport between Scheduler and Runner.
//
// Enqueue is NON-BLOCKING — at-capacity yields ErrQueueFull.
// Dequeue BLOCKS until a delivery is available, ctx is cancelled,
// or the queue is closed.
//
// Ack MUST be called by the consumer after a successful end-to-end
// processing of the Delivery. Until Ack is called the message
// remains "in-flight" in the consumer group; if the worker dies
// before ack, the message becomes redeliverable.
//
// Settle — Sprint 5. Hands the queue a structured outcome (reason
// slug + classified FailureType). The queue decides Retry vs Fail
// based on FailureType.Retryable() + attempts left. This replaces
// the looser Sprint 4 contract where the runner picked Retry vs
// Fail directly; the runner now just reports WHAT happened, and
// the queue interprets policy.
//
// Retry / Fail remain on the interface for backwards compat with
// the Sprint 4 in-memory tests + for the queue adapter's own
// internal use (Retry on exhausted attempts promotes to Fail).
type JobQueue interface {
	Enqueue(ctx context.Context, job syncdom.SyncJob) error
	Dequeue(ctx context.Context) (Delivery, error)
	Ack(ctx context.Context, d Delivery) error
	Settle(ctx context.Context, d Delivery, reason string) error
	Retry(ctx context.Context, d Delivery, reason string) error
	Fail(ctx context.Context, d Delivery, reason string) error
	Len() int
	Close()
}

// QueueStats — Sprint 4. Optional surface for the /v1/scheduler/status
// endpoint. Implementations that don't have a notion (e.g.
// in-memory) return zeroed values + Connected=true. The Redis
// adapter reports real values.
type QueueStats struct {
	Connected       bool
	StreamDepth     int64
	PendingMessages int64
	RetryQueueSize  int64
	ActiveConsumers int64
}

// StatsReporter — implementations may also report stats. The HTTP
// handler checks via a type assertion; in-memory queues that don't
// implement it report Connected=true with zeros.
type StatsReporter interface {
	Stats(ctx context.Context) QueueStats
}
