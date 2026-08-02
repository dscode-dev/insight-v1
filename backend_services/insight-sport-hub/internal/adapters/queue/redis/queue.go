// Redis Streams JobQueue — Sprint 4.
//
// Implements ports.JobQueue using:
//   - one stream                         (XADD producer, XREADGROUP consumer)
//   - one consumer group                 (single logical group for Sprint 4)
//   - one sorted set for retry timing    (ZADD on Retry, promoter polls)
//   - one DLQ port for terminal failures (Sprint 4: NoopDLQ default)
//
// Architectural guarantees preserved from the in-memory adapter:
//   - FIFO ordering — Redis streams are append-only
//   - bounded capacity — XADD MAXLEN ~ N trims oldest
//   - non-blocking Enqueue — XADD on local client is sub-ms
//   - blocking Dequeue with ctx cancel — XREADGROUP BLOCK + ctx
//   - graceful Close — stops the promoter + signals workers
//   - Len() visibility — XLEN (approximate due to MAXLEN trimming)
//
// No application package imports Redis. The composition root chooses
// this adapter or the in-memory one; the scheduler / runner / planner
// / dispatcher / limiter never know which is active.
package redis

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/rs/zerolog"

	goredis "github.com/redis/go-redis/v9"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// RedisQueue satisfies ports.JobQueue + ports.StatsReporter.
type RedisQueue struct {
	client *goredis.Client
	cfg    Config
	dlq    ports.DeadLetterStore
	logger zerolog.Logger

	done chan struct{}
	once sync.Once
	wg   sync.WaitGroup

	connected atomic.Bool

	// Sprint 5.1 — optional pending-message claimer (Part 6). nil
	// when ClaimerConfig.Enabled is false. Stats() incorporates the
	// claimer's counters when present.
	claimer *Claimer
}

// New constructs a RedisQueue + ensures the consumer group exists +
// starts the retry promoter goroutine. Returns an error if the
// initial PING fails — boot fails loudly rather than silently
// limping along disconnected.
func New(
	ctx context.Context,
	cfg Config,
	dlq ports.DeadLetterStore,
	logger zerolog.Logger,
) (*RedisQueue, error) {
	cfg = cfg.Defaults()
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	if dlq == nil {
		return nil, errors.New("redis queue: DLQ store required")
	}
	client := goredis.NewClient(&goredis.Options{
		Addr:        cfg.Addr,
		Password:    cfg.Password,
		DB:          cfg.DB,
		DialTimeout: cfg.DialTimeout,
	})

	if err := client.Ping(ctx).Err(); err != nil {
		_ = client.Close()
		return nil, fmt.Errorf("redis queue: ping: %w", err)
	}
	logger.Info().
		Str("addr", cfg.Addr).
		Str("stream", cfg.Stream).
		Str("group", cfg.Group).
		Str("consumer", cfg.ConsumerName).
		Msg("redis_connected")

	if err := ensureGroup(ctx, client, cfg); err != nil {
		_ = client.Close()
		return nil, err
	}

	q := &RedisQueue{
		client: client,
		cfg:    cfg,
		dlq:    dlq,
		logger: logger,
		done:   make(chan struct{}),
	}
	q.connected.Store(true)

	q.wg.Add(1)
	go q.runPromoter()

	// Sprint 5.1 — pending-message claimer. Optional; when enabled,
	// the claimer takes over abandoned PEL entries after MinIdleTime
	// so a worker crash doesn't leave jobs stuck in pending forever.
	if cfg.Claimer.Enabled {
		q.claimer = newClaimer(q, cfg.Claimer, logger)
		q.wg.Add(1)
		go q.claimer.run()
	}

	return q, nil
}

// runPromoter — background goroutine that periodically scans the
// retry sorted set + XADDs ready entries to the stream. Exits on
// Close.
func (q *RedisQueue) runPromoter() {
	defer q.wg.Done()
	t := time.NewTicker(q.cfg.PromoterInterval)
	defer t.Stop()
	for {
		select {
		case <-q.done:
			return
		case <-t.C:
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			n, err := promoteReadyRetries(ctx, q.client, q.cfg, time.Now(), 100)
			cancel()
			if err != nil {
				q.logger.Warn().Err(err).Msg("redis_retry_promoter_failed")
				continue
			}
			if n > 0 {
				q.logger.Debug().Int("promoted", n).Msg("redis_retries_promoted")
			}
		}
	}
}

// Enqueue — XADD to the stream. Non-blocking; at-capacity is
// approximated by MAXLEN trimming (older entries drop, newer
// entries persist) so we never return ErrQueueFull from Redis. The
// behaviour matches the spec's "bounded capacity semantics" since
// the queue is bounded by MaxLen.
func (q *RedisQueue) Enqueue(ctx context.Context, job syncdom.SyncJob) error {
	select {
	case <-q.done:
		return ports.ErrQueueClosed
	default:
	}
	_, err := xadd(ctx, q.client, q.cfg, job)
	if err != nil {
		q.logger.Warn().Err(err).
			Str("job_id", job.JobID.String()).
			Msg("job_publish_failed")
		return err
	}
	q.logger.Info().
		Str("stream", q.cfg.Stream).
		Str("provider", job.ProviderID).
		Str("sync_type", string(job.SyncType)).
		Str("job_id", job.JobID.String()).
		Msg("job_published")
	return nil
}

// Dequeue blocks until a delivery is available, ctx is cancelled,
// or the queue is closed. Internally loops over XREADGROUP BLOCK
// timeouts so the call observes both ctx + done channels promptly.
func (q *RedisQueue) Dequeue(ctx context.Context) (ports.Delivery, error) {
	for {
		select {
		case <-q.done:
			return ports.Delivery{}, ports.ErrQueueClosed
		case <-ctx.Done():
			return ports.Delivery{}, ctx.Err()
		default:
		}

		id, values, err := xreadGroupOne(ctx, q.client, q.cfg)
		if err != nil {
			if errors.Is(err, errBlockTimeout) {
				continue
			}
			if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
				return ports.Delivery{}, err
			}
			q.connected.Store(false)
			q.logger.Warn().Err(err).Msg("redis_disconnected")
			return ports.Delivery{}, err
		}
		q.connected.Store(true)

		job, err := decodeJob(values)
		if err != nil {
			// Malformed payload — XACK + skip so it doesn't poison
			// the pending list.
			_ = ack(ctx, q.client, q.cfg, id)
			q.logger.Warn().Err(err).Str("id", id).Msg("redis_skipped_malformed")
			continue
		}
		q.logger.Info().
			Str("stream", q.cfg.Stream).
			Str("consumer", q.cfg.ConsumerName).
			Str("provider", job.ProviderID).
			Str("sync_type", string(job.SyncType)).
			Str("job_id", job.JobID.String()).
			Str("delivery_id", id).
			Int("attempt", job.CurrentAttempt+1).
			Msg("job_received")
		return ports.Delivery{
			Job:      job,
			Attempt:  job.CurrentAttempt + 1,
			AckToken: id,
		}, nil
	}
}

// Settle — Sprint 5 structured outcome routing. Classifies via
// syncdom.ClassifyReason; retryable → Retry (queue may promote to
// Fail when attempts are exhausted); non-retryable → Fail straight
// to the DLQ.
func (q *RedisQueue) Settle(ctx context.Context, d ports.Delivery, reason string) error {
	ft := syncdom.ClassifyReason(reason)
	if !ft.Retryable() {
		return q.Fail(ctx, d, reason)
	}
	return q.Retry(ctx, d, reason)
}

// Ack — XACK the delivery's stream id. Called by the runner after
// successful end-to-end processing.
func (q *RedisQueue) Ack(ctx context.Context, d ports.Delivery) error {
	if err := ack(ctx, q.client, q.cfg, d.AckToken); err != nil {
		q.logger.Warn().Err(err).Str("delivery_id", d.AckToken).Msg("job_ack_failed")
		return err
	}
	q.logger.Info().
		Str("delivery_id", d.AckToken).
		Str("job_id", d.Job.JobID.String()).
		Msg("job_acknowledged")
	return nil
}

// Retry — ACK the original + ZADD a retry-stamped copy.
// AttemptsExhausted short-circuits to Fail.
func (q *RedisQueue) Retry(ctx context.Context, d ports.Delivery, reason string) error {
	if d.Job.AttemptsExhausted() {
		return q.Fail(ctx, d, reason)
	}
	next := d.Job.PreparedForRetry(time.Now())
	if err := zaddRetry(ctx, q.client, q.cfg, next); err != nil {
		q.logger.Warn().Err(err).Msg("redis_retry_zadd_failed")
		return err
	}
	// ACK the original so it leaves the pending list.
	if err := ack(ctx, q.client, q.cfg, d.AckToken); err != nil {
		// Best effort — log + continue. The retry is already queued
		// in the zset; the original will surface as pending and be
		// claimed eventually (Sprint 5 will add explicit claim logic).
		q.logger.Warn().Err(err).Msg("redis_retry_original_ack_failed")
	}
	q.logger.Info().
		Str("job_id", next.JobID.String()).
		Int("attempt", next.CurrentAttempt).
		Int("max_attempts", next.MaxAttempts).
		Time("retry_after", next.RetryAfter).
		Str("reason", reason).
		Msg("job_retry_scheduled")
	return nil
}

// Fail — record via DLQ port + ACK the delivery. Terminal.
func (q *RedisQueue) Fail(ctx context.Context, d ports.Delivery, reason string) error {
	failure, err := syncdom.NewSyncJobFailure(d.Job, reason, time.Now())
	if err != nil {
		return fmt.Errorf("redis queue: build failure: %w", err)
	}
	if derr := q.dlq.Record(ctx, failure); derr != nil {
		q.logger.Warn().Err(derr).
			Str("job_id", d.Job.JobID.String()).
			Msg("dead_letter_record_failed")
	}
	if err := ack(ctx, q.client, q.cfg, d.AckToken); err != nil {
		q.logger.Warn().Err(err).
			Str("delivery_id", d.AckToken).
			Msg("job_fail_ack_failed")
	}
	q.logger.Warn().
		Str("job_id", d.Job.JobID.String()).
		Int("attempts", d.Job.CurrentAttempt).
		Str("reason", reason).
		Msg("job_processing_failed")
	return nil
}

// Len — XLEN of the stream. Approximate due to MAXLEN trimming;
// the spec explicitly allows "internally approximated".
func (q *RedisQueue) Len() int {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	return int(streamDepth(ctx, q.client, q.cfg))
}

// Close — idempotent shutdown. Stops the promoter, flips the done
// channel (Dequeue + Enqueue see ErrQueueClosed), waits for the
// promoter to finish, then closes the underlying redis client.
//
// In-flight Dequeue calls observe ctx OR done — they exit cleanly.
// In-flight Ack / Retry / Fail / Enqueue continue against the live
// client because Close returns AFTER the promoter wg.Wait, giving
// running operations time to flush.
func (q *RedisQueue) Close() {
	q.once.Do(func() {
		close(q.done)
		q.wg.Wait()
		_ = q.client.Close()
		q.logger.Info().Msg("redis_disconnected")
	})
}

// Stats — Sprint 4 admin surface. ALWAYS returns; never blocks the
// HTTP request longer than a short ctx.
func (q *RedisQueue) Stats(ctx context.Context) ports.QueueStats {
	scoped, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	connected := q.connected.Load() && pingHealthy(scoped, q.client)
	if !connected {
		return ports.QueueStats{Connected: false}
	}
	return ports.QueueStats{
		Connected:       true,
		StreamDepth:     streamDepth(scoped, q.client, q.cfg),
		PendingMessages: pendingCount(scoped, q.client, q.cfg),
		RetryQueueSize:  retryDepth(scoped, q.client, q.cfg),
		ActiveConsumers: consumersCount(scoped, q.client, q.cfg),
	}
}
