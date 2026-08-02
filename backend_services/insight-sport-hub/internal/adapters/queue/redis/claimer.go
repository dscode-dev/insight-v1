// Pending-message claimer — Sprint 5.1 Part 6.
//
// Closes the worker-crash window: when a consumer goes down mid-job
// its pending entries sit in the consumer-group's PEL forever. The
// claimer periodically scans XPENDING for entries idle longer than
// MinIdleTime and XCLAIMs them onto the local consumer name so
// another worker can finish them.
//
// Architectural rule: the claimer is internal to the Redis adapter
// — no application package imports it. The runner just consumes
// the queue via the existing ports.JobQueue interface; reclaimed
// messages flow through XREADGROUP the same way fresh ones do.
//
// Duplicate-execution prevention:
//   - XCLAIM atomically reassigns ownership; the original consumer
//     can no longer XACK the same id.
//   - The retry counter lives INSIDE the message payload
//     (SyncJob.CurrentAttempt) — XCLAIM does not increment it; the
//     worker that picks the claim up sees the same attempt number
//     it would have seen on the original delivery, so the runner's
//     "attempts exhausted" check stays consistent.
//   - XCLAIM does increment the message's Redis-side delivery
//     counter, which we cap via MaxDeliveries: a runaway claim
//     loop after MaxDeliveries gets routed to Fail (DLQ).
package redis

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
)

// ClaimerConfig — Sprint 5.1 knobs.
type ClaimerConfig struct {
	// Enabled — false disables the claimer entirely (Sprint 4
	// behaviour). When false the queue still runs; it just has no
	// crash-recovery fallback.
	Enabled bool

	// MinIdleTime — claim entries idle for at least this long. Should
	// be > the maximum job runtime so we don't claim entries that
	// are still being worked. 30s is the conventional default.
	MinIdleTime time.Duration

	// Interval — how often to run a claim sweep. 5s gives prompt
	// recovery without hammering Redis.
	Interval time.Duration

	// BatchSize — XPENDING + XCLAIM in batches of this many. Caps
	// the work per sweep + bounds memory.
	BatchSize int64

	// MaxDeliveries — after this many redeliveries, the message is
	// considered poison. The claimer routes it via Fail() (DLQ) and
	// XACKs the original so it stops cycling.
	MaxDeliveries int64
}

func (c ClaimerConfig) Defaults() ClaimerConfig {
	if c.MinIdleTime <= 0 {
		c.MinIdleTime = 30 * time.Second
	}
	if c.Interval <= 0 {
		c.Interval = 5 * time.Second
	}
	if c.BatchSize <= 0 {
		c.BatchSize = 64
	}
	if c.MaxDeliveries <= 0 {
		c.MaxDeliveries = 8
	}
	return c
}

// Claimer is started by the RedisQueue when constructed with a
// non-nil ClaimerConfig. Runs in its own goroutine; observes the
// queue's done channel for shutdown.
type Claimer struct {
	queue  *RedisQueue
	cfg    ClaimerConfig
	logger zerolog.Logger

	mu              sync.Mutex
	reclaimedTotal  int64
	deadLetteredTot int64
	lastSweepAt     time.Time
}

func newClaimer(q *RedisQueue, cfg ClaimerConfig, logger zerolog.Logger) *Claimer {
	return &Claimer{
		queue:  q,
		cfg:    cfg.Defaults(),
		logger: logger,
	}
}

// run is the supervised loop. Exits when q.done closes.
func (c *Claimer) run() {
	defer c.queue.wg.Done()
	t := time.NewTicker(c.cfg.Interval)
	defer t.Stop()
	c.logger.Info().
		Dur("min_idle", c.cfg.MinIdleTime).
		Dur("interval", c.cfg.Interval).
		Int64("max_deliveries", c.cfg.MaxDeliveries).
		Msg("redis_claimer_started")
	for {
		select {
		case <-c.queue.done:
			c.logger.Info().Msg("redis_claimer_stopped")
			return
		case <-t.C:
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			n, err := c.sweep(ctx)
			cancel()
			if err != nil {
				c.logger.Warn().Err(err).Msg("redis_claimer_sweep_failed")
				continue
			}
			if n > 0 {
				c.logger.Info().Int("claimed", n).Msg("redis_claimer_swept")
			}
		}
	}
}

// sweep claims every PEL entry idle for at least MinIdleTime. For
// each entry: if deliveries exceeded MaxDeliveries, route via the
// DLQ; otherwise XCLAIM to the local consumer so XREADGROUP picks
// it up on the next read.
//
// Returns the number of entries the claimer touched (claimed +
// dead-lettered).
func (c *Claimer) sweep(ctx context.Context) (int, error) {
	c.mu.Lock()
	c.lastSweepAt = time.Now()
	c.mu.Unlock()

	pending, err := c.queue.client.XPendingExt(ctx, &goredis.XPendingExtArgs{
		Stream: c.queue.cfg.Stream,
		Group:  c.queue.cfg.Group,
		Idle:   c.cfg.MinIdleTime,
		Start:  "-",
		End:    "+",
		Count:  c.cfg.BatchSize,
	}).Result()
	if err != nil {
		if errors.Is(err, goredis.Nil) {
			return 0, nil
		}
		return 0, fmt.Errorf("xpending: %w", err)
	}
	if len(pending) == 0 {
		return 0, nil
	}
	touched := 0
	for _, p := range pending {
		// Poison guard: too many redeliveries → dead-letter.
		if p.RetryCount > c.cfg.MaxDeliveries {
			if err := c.deadLetter(ctx, p.ID); err != nil {
				c.logger.Warn().Err(err).
					Str("entry_id", p.ID).
					Msg("redis_claimer_dead_letter_failed")
				continue
			}
			c.mu.Lock()
			c.deadLetteredTot++
			c.mu.Unlock()
			touched++
			continue
		}
		// Hand the entry to the local consumer so it shows up on the
		// next XREADGROUP. JustID=true keeps the response light —
		// we don't need the payload, we just want ownership.
		claimed, err := c.queue.client.XClaimJustID(ctx, &goredis.XClaimArgs{
			Stream:   c.queue.cfg.Stream,
			Group:    c.queue.cfg.Group,
			Consumer: c.queue.cfg.ConsumerName,
			MinIdle:  c.cfg.MinIdleTime,
			Messages: []string{p.ID},
		}).Result()
		if err != nil {
			c.logger.Warn().Err(err).Str("entry_id", p.ID).Msg("redis_xclaim_failed")
			continue
		}
		if len(claimed) > 0 {
			c.mu.Lock()
			c.reclaimedTotal++
			c.mu.Unlock()
			touched++
			c.logger.Info().
				Str("entry_id", p.ID).
				Str("from_consumer", p.Consumer).
				Str("to_consumer", c.queue.cfg.ConsumerName).
				Int64("deliveries", p.RetryCount).
				Msg("redis_message_reclaimed")
		}
	}
	return touched, nil
}

// deadLetter — the entry is poison. Best-effort: read the payload,
// hand to the DLQ via the queue's Fail path, then XACK so it stops
// cycling. If we can't read the payload (already deleted) we just
// XACK so it stops re-delivering.
func (c *Claimer) deadLetter(ctx context.Context, entryID string) error {
	rows, err := c.queue.client.XRange(ctx, c.queue.cfg.Stream, entryID, entryID).Result()
	if err == nil && len(rows) == 1 {
		job, derr := decodeJob(rows[0].Values)
		if derr == nil {
			// Build a ports.Delivery the queue.Fail path can use to
			// construct the SyncJobFailure with proper provenance.
			// The claimer reports "attempts_exhausted" which the
			// classifier (syncdom.ClassifyReason) maps to
			// FailurePermanent — exactly what we want.
			d := deliveryFromClaim(job, entryID)
			if err := c.queue.Fail(ctx, d, "attempts_exhausted"); err != nil {
				return err
			}
			return nil
		}
	}
	// Couldn't decode — just clear the pending entry so it stops
	// cycling. Log so ops can see the orphan.
	if err := c.queue.client.XAck(ctx, c.queue.cfg.Stream,
		c.queue.cfg.Group, entryID).Err(); err != nil {
		return err
	}
	c.logger.Warn().Str("entry_id", entryID).Msg("redis_orphaned_pending_acked")
	return nil
}

// claimerStats is read by the queue's Stats() for the
// /v1/scheduler/status admin endpoint.
type claimerStats struct {
	ReclaimedTotal    int64
	DeadLetteredTotal int64
	LastSweepAt       time.Time
}

func (c *Claimer) stats() claimerStats {
	c.mu.Lock()
	defer c.mu.Unlock()
	return claimerStats{
		ReclaimedTotal:    c.reclaimedTotal,
		DeadLetteredTotal: c.deadLetteredTot,
		LastSweepAt:       c.lastSweepAt,
	}
}
