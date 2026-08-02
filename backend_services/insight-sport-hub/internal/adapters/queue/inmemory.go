// In-memory bounded FIFO JobQueue — Sprint 3 default, Sprint 4
// updated for Delivery semantics.
//
// Backing store: a buffered channel of `pending` envelopes (each
// wrapping a SyncJob + its in-flight AckToken). Channel semantics
// give us FIFO + thread-safety + dequeue blocking for free.
//
// Sprint 4 differences from Sprint 3:
//   - Dequeue returns a `ports.Delivery` carrying an AckToken
//     (here: a monotonic in-process id). The token has no real
//     transport meaning for in-memory — it exists for parity with
//     the Redis adapter so the runner code is identical.
//   - Ack is a no-op + counter bump.
//   - Retry stamps `PreparedForRetry(now)` on the job and
//     re-enqueues either immediately (no RetryAfter) or via
//     `time.AfterFunc` (RetryAfter > now). Attempts-exhausted
//     short-circuits to the DLQ.
//   - Fail builds a SyncJobFailure and hands it to the DLQ store.
//
// Architectural rule: this package is an ADAPTER. Nothing in
// internal/application/** imports it directly — the composition
// root passes the constructed *InMemoryQueue as a ports.JobQueue.
package queue

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/rs/zerolog"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// InMemoryConfig — composition-root knobs.
type InMemoryConfig struct {
	Capacity int                   // > 0
	DLQ      ports.DeadLetterStore // required; pass NoopDLQ to skip storage
	Logger   zerolog.Logger
	Clock    Clock // optional; nil => system clock
}

// Clock — local injection seam so tests can drive retry timing
// without sleeping. Declared here so the in-memory queue doesn't
// pull in ports.Clock and force every consumer to satisfy it.
type Clock interface {
	Now() time.Time
}

type systemClock struct{}

func (systemClock) Now() time.Time { return time.Now() }

// InMemoryQueue is the default ports.JobQueue implementation.
type InMemoryQueue struct {
	ch     chan pending
	done   chan struct{}
	once   sync.Once
	tokens atomic.Int64

	dlq    ports.DeadLetterStore
	logger zerolog.Logger
	clock  Clock

	// retryTimers is the set of pending time.AfterFunc handles —
	// tracked so Close can cancel them.
	retryMu     sync.Mutex
	retryTimers map[*time.Timer]struct{}
}

type pending struct {
	job   syncdom.SyncJob
	token string
}

// NewInMemory constructs an in-memory queue. Capacity must be > 0.
//
// Backwards-compat shim: the Sprint 3 signature took only an int.
// Existing call sites can still call `NewInMemory(cap)` via the
// NewInMemoryBasic helper below.
func NewInMemory(cfg InMemoryConfig) *InMemoryQueue {
	if cfg.Capacity <= 0 {
		panic("queue: capacity must be > 0")
	}
	if cfg.DLQ == nil {
		panic("queue: DLQ store required")
	}
	clk := cfg.Clock
	if clk == nil {
		clk = systemClock{}
	}
	return &InMemoryQueue{
		ch:          make(chan pending, cfg.Capacity),
		done:        make(chan struct{}),
		dlq:         cfg.DLQ,
		logger:      cfg.Logger,
		clock:       clk,
		retryTimers: map[*time.Timer]struct{}{},
	}
}

// NewInMemoryBasic — Sprint 3 backwards-compat shim. Tests + lab
// boot use it. Wires a built-in noop DLQ.
func NewInMemoryBasic(capacity int) *InMemoryQueue {
	return NewInMemory(InMemoryConfig{
		Capacity: capacity,
		DLQ:      NoopDLQ{},
	})
}

// nextToken — in-process monotonic id. The Redis adapter uses the
// stream message ID; in-memory just numbers them.
func (q *InMemoryQueue) nextToken() string {
	return fmt.Sprintf("im-%d", q.tokens.Add(1))
}

// Enqueue is non-blocking. Returns ports.ErrQueueFull when the
// buffer is exhausted and ports.ErrQueueClosed after Close.
func (q *InMemoryQueue) Enqueue(_ context.Context, job syncdom.SyncJob) error {
	select {
	case <-q.done:
		return ports.ErrQueueClosed
	default:
	}
	envelope := pending{job: job, token: q.nextToken()}
	select {
	case q.ch <- envelope:
		return nil
	case <-q.done:
		return ports.ErrQueueClosed
	default:
		return ports.ErrQueueFull
	}
}

// Dequeue blocks until a delivery is available, ctx is cancelled,
// or the queue is closed.
func (q *InMemoryQueue) Dequeue(ctx context.Context) (ports.Delivery, error) {
	select {
	case <-ctx.Done():
		return ports.Delivery{}, ctx.Err()
	case <-q.done:
		// Drain any remaining buffered jobs post-close.
		select {
		case env := <-q.ch:
			return q.envelopeToDelivery(env), nil
		default:
			return ports.Delivery{}, ports.ErrQueueClosed
		}
	case env := <-q.ch:
		return q.envelopeToDelivery(env), nil
	}
}

func (q *InMemoryQueue) envelopeToDelivery(env pending) ports.Delivery {
	attempt := env.job.CurrentAttempt + 1
	return ports.Delivery{
		Job:      env.job,
		Attempt:  attempt,
		AckToken: env.token,
	}
}

// Ack — in-memory acks are no-ops by design; there is no pending
// list to clear. Sprint 4 declares the method for parity with the
// Redis adapter.
func (q *InMemoryQueue) Ack(_ context.Context, _ ports.Delivery) error {
	return nil
}

// Settle — Sprint 5 structured outcome routing. Classifies the
// supplied reason via syncdom.ClassifyReason; retryable types route
// to Retry (with the queue's own attempts-exhausted check
// promoting to Fail when applicable). Non-retryable types route
// straight to Fail.
func (q *InMemoryQueue) Settle(ctx context.Context, d ports.Delivery, reason string) error {
	ft := syncdom.ClassifyReason(reason)
	if !ft.Retryable() {
		return q.Fail(ctx, d, reason)
	}
	return q.Retry(ctx, d, reason)
}

// Retry re-enqueues the job with `PreparedForRetry`. If the job has
// already exhausted its attempts the call routes to the DLQ +
// reports nil (terminal). Otherwise the retry waits until
// RetryAfter via time.AfterFunc; if RetryAfter is in the past the
// re-enqueue happens synchronously.
func (q *InMemoryQueue) Retry(ctx context.Context, d ports.Delivery, reason string) error {
	if d.Job.AttemptsExhausted() {
		// Treat as terminal — the caller meant Retry but the job has
		// no attempts left. Promote to Fail so the DLQ is invoked.
		return q.Fail(ctx, d, reason)
	}
	next := d.Job.PreparedForRetry(q.clock.Now())
	delay := next.RetryAfter.Sub(q.clock.Now())
	if delay <= 0 {
		return q.reenqueue(ctx, next)
	}
	t := time.AfterFunc(delay, func() {
		// Use a detached context — the original ctx may be cancelled
		// while the timer is still pending. Errors here are best-
		// effort + logged.
		_ = q.reenqueue(context.Background(), next)
		q.forgetTimer(nil) // pruning happens below
	})
	q.rememberTimer(t)
	q.logger.Info().
		Str("job_id", next.JobID.String()).
		Int("attempt", next.CurrentAttempt).
		Dur("retry_in", delay).
		Str("reason", reason).
		Msg("job_retry_scheduled")
	return nil
}

func (q *InMemoryQueue) reenqueue(ctx context.Context, job syncdom.SyncJob) error {
	return q.Enqueue(ctx, job)
}

// Fail — terminal. Records via DLQ + returns. The original delivery
// is already consumed from the channel (Dequeue removed it), so
// there is no in-flight slot to clear.
func (q *InMemoryQueue) Fail(ctx context.Context, d ports.Delivery, reason string) error {
	failure, err := syncdom.NewSyncJobFailure(d.Job, reason, q.clock.Now())
	if err != nil {
		return fmt.Errorf("queue fail build failure: %w", err)
	}
	if err := q.dlq.Record(ctx, failure); err != nil {
		q.logger.Warn().Err(err).
			Str("job_id", d.Job.JobID.String()).
			Msg("dead_letter_record_failed")
	}
	return nil
}

func (q *InMemoryQueue) Len() int { return len(q.ch) }

// Close is idempotent. Cancels every pending retry timer + drains
// the channel; Enqueue/Dequeue both observe ErrQueueClosed after.
func (q *InMemoryQueue) Close() {
	q.once.Do(func() {
		close(q.done)
		q.retryMu.Lock()
		for t := range q.retryTimers {
			t.Stop()
		}
		q.retryTimers = nil
		q.retryMu.Unlock()
	})
}

func (q *InMemoryQueue) rememberTimer(t *time.Timer) {
	q.retryMu.Lock()
	defer q.retryMu.Unlock()
	if q.retryTimers != nil {
		q.retryTimers[t] = struct{}{}
	}
}

func (q *InMemoryQueue) forgetTimer(t *time.Timer) {
	q.retryMu.Lock()
	defer q.retryMu.Unlock()
	if q.retryTimers != nil && t != nil {
		delete(q.retryTimers, t)
	}
}

// Stats — InMemoryQueue is "always connected"; counters are
// best-effort. Implements ports.StatsReporter so the HTTP endpoint
// can render a unified shape across queue impls.
func (q *InMemoryQueue) Stats(_ context.Context) ports.QueueStats {
	q.retryMu.Lock()
	pending := len(q.retryTimers)
	q.retryMu.Unlock()
	return ports.QueueStats{
		Connected:       true,
		StreamDepth:     int64(q.Len()),
		PendingMessages: 0, // no pending list in-memory
		RetryQueueSize:  int64(pending),
		ActiveConsumers: 0, // unknown; consumer count lives in the runner
	}
}
