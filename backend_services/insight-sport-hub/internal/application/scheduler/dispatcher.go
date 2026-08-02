// Dispatcher — Sprint 3.
//
// Thin shim between the Planner output (a slice of SyncJob) and the
// JobQueue. Kept as a separate type so the scheduler tick stays
// short + so the metrics/logging concern doesn't bleed into the
// queue port.
//
// Future evolution: the dispatcher is the seam at which dispatching
// becomes distributed — Sprint 4+ will swap the queue for Redis
// Streams; admin tooling may also inject priority-based reordering
// here. Both changes happen WITHOUT touching the Planner.
package scheduler

import (
	"context"
	"errors"

	"github.com/rs/zerolog"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// Dispatcher pushes planned jobs into the queue. It records per-job
// outcomes to the status recorder so the admin endpoint can show
// queued counts immediately after a tick.
type Dispatcher struct {
	queue  ports.JobQueue
	status QueueStatusRecorder
	logger zerolog.Logger
}

// QueueStatusRecorder — narrow interface the dispatcher needs from
// the observability subsystem. Defined locally so the scheduler
// package doesn't pull in the full ProviderStatus surface (and the
// boundary remains explicit).
type QueueStatusRecorder interface {
	IncQueued(sourceID string)
	IncQueueDropped(sourceID string, reason string)
}

func NewDispatcher(
	queue ports.JobQueue,
	status QueueStatusRecorder,
	logger zerolog.Logger,
) *Dispatcher {
	return &Dispatcher{queue: queue, status: status, logger: logger}
}

// Dispatch enqueues every job in the slice. Per-job errors are
// logged + counted; the call returns the count of successfully
// enqueued jobs so the caller can record the tick outcome.
//
// Enqueue is non-blocking; an at-capacity queue drops the job, which
// is fine — the next tick reschedules anything still due.
func (d *Dispatcher) Dispatch(ctx context.Context, jobs []syncdom.SyncJob) (int, error) {
	dispatched := 0
	for _, job := range jobs {
		err := d.queue.Enqueue(ctx, job)
		switch {
		case err == nil:
			d.status.IncQueued(job.ProviderID)
			d.logger.Info().
				Str("provider", job.ProviderID).
				Str("competition", job.CompetitionID.String()).
				Str("sync_type", string(job.SyncType)).
				Str("job_id", job.JobID.String()).
				Int("queue_size", d.queue.Len()).
				Msg("job_queued")
			dispatched++
		case errors.Is(err, ports.ErrQueueFull):
			d.status.IncQueueDropped(job.ProviderID, "queue_full")
			d.logger.Warn().
				Str("provider", job.ProviderID).
				Str("sync_type", string(job.SyncType)).
				Msg("job_dropped_queue_full")
		case errors.Is(err, ports.ErrQueueClosed):
			// Shutdown in progress — stop dispatching the rest.
			return dispatched, err
		default:
			d.status.IncQueueDropped(job.ProviderID, "enqueue_error")
			d.logger.Error().Err(err).
				Str("provider", job.ProviderID).
				Msg("job_dispatch_failed")
		}
	}
	return dispatched, nil
}
