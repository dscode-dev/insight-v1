// Package scheduler — Sprint 3 orchestration entry point.
//
// The Scheduler owns the periodic tick loop. Each tick:
//  1. Asks the Planner what's due.
//  2. Hands the planned SyncJobs to the Dispatcher.
//  3. Records the tick outcome (count, duration) for observability.
//
// Lifetime:
//   - Run(ctx) blocks until ctx is cancelled. On cancel it stops the
//     ticker, finishes the in-flight tick, then returns ctx.Err().
//   - Sibling goroutines (the JobRunner workers) live in their own
//     packages and observe the same ctx for graceful shutdown.
//
// Architectural rule: the Scheduler decides WHEN. It NEVER decides
// IF (RateLimiter) and NEVER decides HOW (adapter). Importing
// `internal/adapters/**` is forbidden (boundary test).
package scheduler

import (
	"context"
	"errors"
	"sync/atomic"
	"time"

	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// Config tunes the scheduler. Interval is the only required field.
type Config struct {
	// Interval between planning ticks. The Scheduler uses a real
	// time.Ticker — no cron lib (per Sprint 3 spec).
	Interval time.Duration
}

// Scheduler is the long-lived loop. Construct with New, run with
// Run, observe state via Snapshot.
type Scheduler struct {
	cfg        Config
	planner    *Planner
	dispatcher *Dispatcher
	logger     zerolog.Logger

	running     atomic.Bool
	tickCount   atomic.Int64
	jobsCreated atomic.Int64
	lastTickAt  atomic.Value // time.Time
}

func New(
	cfg Config,
	planner *Planner,
	dispatcher *Dispatcher,
	logger zerolog.Logger,
) *Scheduler {
	if cfg.Interval <= 0 {
		cfg.Interval = 30 * time.Second
	}
	return &Scheduler{
		cfg:        cfg,
		planner:    planner,
		dispatcher: dispatcher,
		logger:     logger,
	}
}

// Run blocks until ctx is cancelled. The first tick fires
// immediately so the system doesn't wait one Interval to start
// emitting jobs at boot.
//
// Graceful shutdown: on ctx.Done() the ticker is stopped and the
// in-flight tick (if any) finishes. Run returns ctx.Err() — main.go
// treats context.Canceled as a clean exit.
func (s *Scheduler) Run(ctx context.Context) error {
	s.running.Store(true)
	defer s.running.Store(false)

	s.logger.Info().
		Dur("interval", s.cfg.Interval).
		Msg("scheduler_started")

	// Immediate first tick — boots the system without waiting.
	s.runTick(ctx)

	ticker := time.NewTicker(s.cfg.Interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			s.logger.Info().
				Int64("ticks", s.tickCount.Load()).
				Int64("jobs_created_total", s.jobsCreated.Load()).
				Msg("scheduler_stopped")
			return ctx.Err()
		case <-ticker.C:
			s.runTick(ctx)
		}
	}
}

// runTick is the body of one tick. Errors are logged but never
// propagated — the loop is best-effort + self-healing.
func (s *Scheduler) runTick(ctx context.Context) {
	start := time.Now()
	s.tickCount.Add(1)
	s.lastTickAt.Store(start)

	jobs, err := s.planner.Plan(ctx)
	if err != nil {
		s.logger.Error().Err(err).Msg("scheduler_tick_plan_failed")
		return
	}

	s.logger.Debug().
		Int("planned", len(jobs)).
		Int64("tick", s.tickCount.Load()).
		Msg("scheduler_tick")

	dispatched, err := s.dispatcher.Dispatch(ctx, jobs)
	if err != nil && !errors.Is(err, ports.ErrQueueClosed) {
		s.logger.Warn().Err(err).Msg("scheduler_tick_dispatch_partial")
	}
	s.jobsCreated.Add(int64(dispatched))

	s.logger.Info().
		Int("planned", len(jobs)).
		Int("dispatched", dispatched).
		Dur("duration", time.Since(start)).
		Msg("scheduler_tick_completed")
}

// Snapshot is read-only — exposed to the /v1/scheduler/status
// handler so the admin UI can render scheduler-level state without
// poking internals.
type Snapshot struct {
	Running          bool
	Interval         time.Duration
	Ticks            int64
	JobsCreatedTotal int64
	LastTickAt       time.Time
}

func (s *Scheduler) Snapshot() Snapshot {
	snap := Snapshot{
		Running:          s.running.Load(),
		Interval:         s.cfg.Interval,
		Ticks:            s.tickCount.Load(),
		JobsCreatedTotal: s.jobsCreated.Load(),
	}
	if v := s.lastTickAt.Load(); v != nil {
		snap.LastTickAt = v.(time.Time)
	}
	return snap
}
