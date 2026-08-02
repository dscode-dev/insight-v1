// Package jobrunner — Sprint 3.
//
// Worker pool that consumes SyncJobs from the JobQueue and walks
// them through the runtime contract:
//
//	Dequeue → RateLimiter.Allow → SourceAdapter.Fetch* → Ingester
//
// The Runner is intentionally thin. It owns NOTHING about how to
// fetch data (that's the adapter), nothing about WHEN to fetch
// (that's the scheduler), and nothing about WHETHER to fetch
// (that's the rate limiter). It is the orchestrator of those four
// collaborators.
//
// Architectural rule (Sprint 3 spec):
//
//	"Runner must not know provider internals.
//	 Runner receives interfaces only."
//
// All collaborators arrive as ports/interfaces; the package never
// imports an adapter package.
package jobrunner

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-sports-hub/internal/application/ratelimit"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// RawIngester is the narrow seam onto the IngestionOrchestrator.
// Declared as a function type so the runner doesn't pull the
// orchestrator's full surface (Result types, validation reasons …)
// into its API. The composition root wraps `orchestrator.IngestRaw`
// into this shape.
type RawIngester func(ctx context.Context, raw *event.RawSportsEvent) error

// StatusRecorder — the runner's view of provider status. Narrow on
// purpose: the runner doesn't need to read snapshots, only mutate
// counters.
type StatusRecorder interface {
	IncStarted(sourceID string)
	IncCompleted(sourceID string, latency time.Duration)
	IncFailed(sourceID string, latency time.Duration, reason string)
	IncRateLimitBlocked(sourceID string, reason string)
}

// Config for the worker pool.
type Config struct {
	Workers int // >0
}

type Runner struct {
	cfg      Config
	queue    ports.JobQueue
	adapters map[string]ports.SourceAdapter
	limiter  ratelimit.Limiter
	ingester RawIngester
	status   StatusRecorder
	logger   zerolog.Logger

	wg sync.WaitGroup
}

func New(
	cfg Config,
	queue ports.JobQueue,
	adapters map[string]ports.SourceAdapter,
	limiter ratelimit.Limiter,
	ingester RawIngester,
	status StatusRecorder,
	logger zerolog.Logger,
) *Runner {
	if cfg.Workers <= 0 {
		cfg.Workers = 2
	}
	return &Runner{
		cfg:      cfg,
		queue:    queue,
		adapters: adapters,
		limiter:  limiter,
		ingester: ingester,
		status:   status,
		logger:   logger,
	}
}

// Run starts the worker pool. Blocks until ctx is cancelled or the
// queue is closed; both paths drain in-flight jobs before returning.
func (r *Runner) Run(ctx context.Context) {
	r.logger.Info().
		Int("workers", r.cfg.Workers).
		Msg("jobrunner_started")

	for i := 0; i < r.cfg.Workers; i++ {
		r.wg.Add(1)
		go r.workerLoop(ctx, i)
	}
	r.wg.Wait()

	r.logger.Info().Msg("jobrunner_stopped")
}

func (r *Runner) workerLoop(ctx context.Context, id int) {
	defer r.wg.Done()
	r.logger.Info().Int("worker", id).Msg("worker_started")
	for {
		delivery, err := r.queue.Dequeue(ctx)
		if err != nil {
			if errors.Is(err, context.Canceled) ||
				errors.Is(err, ports.ErrQueueClosed) ||
				errors.Is(err, context.DeadlineExceeded) {
				r.logger.Info().Int("worker", id).Msg("worker_stopped")
				return
			}
			r.logger.Warn().Err(err).
				Int("worker", id).
				Msg("dequeue_failed")
			continue
		}
		r.execute(ctx, delivery)
	}
}

// execute runs one delivery end-to-end + dispatches the right
// terminal call (Ack / Retry / Fail) onto the queue. The runner
// owns the message lifecycle — the queue is just transport.
//
// Sprint 4 outcome matrix:
//   - rate-limit blocked → Retry (transient; quota will refill)
//   - unknown provider  → Fail  (terminal; nothing to retry against)
//   - adapter fetch err → Retry (most provider errors are transient)
//   - ingest error per raw → logged + skipped; job still completes Ack
//   - happy path → Ack
//
// AttemptsExhausted upgrades any Retry to Fail inside the queue
// adapter itself — the runner doesn't track attempts.
func (r *Runner) execute(ctx context.Context, delivery ports.Delivery) {
	job := delivery.Job
	start := time.Now()
	logger := r.logger.With().
		Str("provider", job.ProviderID).
		Str("competition", job.CompetitionID.String()).
		Str("sync_type", string(job.SyncType)).
		Str("job_id", job.JobID.String()).
		Int("attempt", delivery.Attempt).
		Str("delivery_id", delivery.AckToken).
		Logger()

	r.status.IncStarted(job.ProviderID)
	logger.Info().Msg("job_started")

	// 1. Rate-limit gate.
	if dec := r.limiter.Allow(job.ProviderID); !dec.Allowed {
		r.status.IncRateLimitBlocked(job.ProviderID, dec.Reason)
		r.status.IncFailed(job.ProviderID, time.Since(start), syncdom.ReasonProviderRateLimit)
		logger.Warn().
			Str("reason", dec.Reason).
			Str("failure_type", string(syncdom.FailureTransient)).
			Msg("rate_limit_blocked")
		// Sprint 5 — Settle delegates the Retry-vs-Fail decision to
		// the queue based on the reason's classification + attempts.
		if err := r.queue.Settle(ctx, delivery, syncdom.ReasonProviderRateLimit); err != nil {
			logger.Warn().Err(err).Msg("settle_failed")
		}
		return
	}

	// 2. Resolve adapter.
	adapter, ok := r.adapters[job.ProviderID]
	if !ok {
		r.status.IncFailed(job.ProviderID, time.Since(start), syncdom.ReasonUnknownProvider)
		logger.Error().
			Str("failure_type", string(syncdom.FailurePermanent)).
			Msg("job_failed_unknown_provider")
		if err := r.queue.Settle(ctx, delivery, syncdom.ReasonUnknownProvider); err != nil {
			logger.Warn().Err(err).Msg("settle_failed")
		}
		return
	}
	logger.Debug().
		Str("adapter_version", adapter.Identity().AdapterVersion).
		Msg("provider_selected")

	// 3. Fetch via adapter (dispatch by sync_type).
	raws, err := r.fetch(ctx, adapter, job)
	if err != nil {
		reason := syncdom.ReasonProviderError
		ft := syncdom.ClassifyReason(reason)
		r.status.IncFailed(job.ProviderID, time.Since(start), reason)
		logger.Warn().Err(err).
			Str("failure_type", string(ft)).
			Dur("execution_duration", time.Since(start)).
			Msg("job_failed")
		if rerr := r.queue.Settle(ctx, delivery, reason); rerr != nil {
			logger.Warn().Err(rerr).Msg("settle_failed")
		}
		return
	}

	// 4. Hand each raw to the ingester. Per-raw failures are logged
	// but don't abort the job — partial ingestion is the right
	// behaviour (one bad fixture shouldn't bin the whole batch).
	ingested := 0
	for _, raw := range raws {
		if raw == nil {
			continue
		}
		if err := r.ingester(ctx, raw); err != nil {
			logger.Warn().Err(err).
				Str("raw_event_id", raw.RawEventID().String()).
				Msg("ingest_failed")
			continue
		}
		ingested++
	}

	if err := r.queue.Ack(ctx, delivery); err != nil {
		logger.Warn().Err(err).Msg("ack_failed")
	}

	r.status.IncCompleted(job.ProviderID, time.Since(start))
	logger.Info().
		Int("raws_fetched", len(raws)).
		Int("raws_ingested", ingested).
		Dur("execution_duration", time.Since(start)).
		Msg("job_completed")
}

// fetch dispatches to the adapter method matching the job's sync_type.
// Unknown sync_type is a domain misuse — surfaces as an error rather
// than a silent skip so it shows up in the failed_jobs counter.
func (r *Runner) fetch(
	ctx context.Context,
	adapter ports.SourceAdapter,
	job syncdom.SyncJob,
) ([]*event.RawSportsEvent, error) {
	switch job.SyncType {
	case syncdom.TypeFixtures, syncdom.TypeResults:
		return adapter.FetchFixtures(ctx, ports.FixtureFetchRequest{
			CompetitionID: job.CompetitionID,
		})
	case syncdom.TypeStandings:
		return adapter.FetchStandings(ctx, ports.StandingsFetchRequest{
			CompetitionID: job.CompetitionID,
		})
	case syncdom.TypeOdds:
		// Odds is an optional capability — only providers that
		// implement ports.OddsAdapter serve it. A provider whose
		// capabilities lied (declared odds but didn't implement the
		// interface) fails loudly here rather than silently skipping.
		oa, ok := adapter.(ports.OddsAdapter)
		if !ok {
			return nil, fmt.Errorf("jobrunner: provider %q does not support odds", job.ProviderID)
		}
		return oa.FetchOdds(ctx, ports.OddsFetchRequest{
			CompetitionID: job.CompetitionID,
		})
	case syncdom.TypeHistoricalOdds:
		ha, ok := adapter.(ports.HistoricalOddsAdapter)
		if !ok {
			return nil, fmt.Errorf("jobrunner: provider %q does not support historical odds", job.ProviderID)
		}
		return ha.FetchHistoricalOdds(ctx, ports.HistoricalOddsFetchRequest{
			CompetitionID: job.CompetitionID,
		})
	default:
		// Capability filter in the Planner should make this
		// unreachable for the configured providers; the explicit
		// error makes test misuse loud.
		return nil, fmt.Errorf("jobrunner: unsupported sync_type %q", job.SyncType)
	}
}
