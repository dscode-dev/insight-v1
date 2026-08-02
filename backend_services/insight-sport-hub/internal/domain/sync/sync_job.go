// SyncJob — Sprint 2.1 contract.
//
// One unit of work the future Scheduler hands to a provider adapter:
// "fetch <SyncType> for <CompetitionID> from <ProviderID> at
// <ScheduledAt>".
//
// CONTRACT ONLY. Sprint 2.1 does NOT:
//   - persist SyncJobs
//   - execute SyncJobs
//   - schedule SyncJobs
//
// The Scheduler (Sprint 3) will own the queue, the worker pool, and
// the retry policy. This type just pins the shape so adapter +
// status surfaces can refer to it stably.
package sync

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// Priority — lower runs first. Conventional values:
//
//	0    critical (manual admin trigger, ops-driven backfill)
//	10   live-window polling (results during a kick-off)
//	50   normal cadence
//	100  background / catalogue refresh
//
// Free-form int so future tiers can slot in without renumbering.
type Priority int

const (
	PriorityCritical   Priority = 0
	PriorityLiveWindow Priority = 10
	PriorityNormal     Priority = 50
	PriorityBackground Priority = 100
)

// JobID is the SyncJob's primary key. Caller-supplied at construction
// so retries can keep the same id without losing audit trail.
type JobID uuid.UUID

func NewJobID() JobID { return JobID(uuid.New()) }

func (j JobID) String() string { return uuid.UUID(j).String() }

// ParseJobID reverses String — used by the DLQ repo when scanning
// persisted ids back into the typed alias.
func ParseJobID(s string) (JobID, error) {
	u, err := uuid.Parse(s)
	if err != nil {
		return JobID{}, err
	}
	return JobID(u), nil
}

// SyncJob describes one scheduled refresh.
//
// All fields are required EXCEPT Metadata (free-form opaque map for
// scheduler-internal hints — never used to drive adapter behaviour).
//
// Sprint 4 — retry fields. MaxAttempts caps the retry chain;
// CurrentAttempt is bumped by the queue adapter when a job is
// re-enqueued for retry. RetryAfter is the earliest UTC time at
// which the retry becomes eligible — the queue enforces it (Redis:
// retry sorted set; in-memory: time.AfterFunc).
type SyncJob struct {
	JobID         JobID
	ProviderID    string // matches Source.SourceID slug
	CompetitionID uuid.UUID
	SyncType      SyncType
	Priority      Priority
	ScheduledAt   time.Time
	Metadata      map[string]string

	// Sprint 4 — retry contract.
	MaxAttempts    int
	CurrentAttempt int
	RetryAfter     time.Time
}

// DefaultMaxAttempts — used by NewSyncJob when the caller doesn't
// specify. 3 attempts is the conventional cap for provider HTTP
// flakes (transient 5xx, rate-limit overruns from a co-tenant).
const DefaultMaxAttempts = 3

// BaseRetryDelay — first retry waits this long; subsequent retries
// double (2x, 4x, …). Adapter implementations call NextRetryDelay
// to compute the per-attempt wait.
const BaseRetryDelay = 5 * time.Second

// NextRetryDelay returns the backoff for the supplied attempt
// number using exponential backoff with base BaseRetryDelay.
// Attempt 1 -> 5s, 2 -> 10s, 3 -> 20s, ...
//
// Caller is the queue adapter (Redis: stamps RetryAfter; in-memory:
// schedules a time.AfterFunc). Pure function — no clock dependency.
func NextRetryDelay(attempt int) time.Duration {
	if attempt < 1 {
		attempt = 1
	}
	// Cap shift to avoid overflow on pathological inputs.
	if attempt > 20 {
		attempt = 20
	}
	return BaseRetryDelay << (attempt - 1)
}

var (
	ErrJobMissingProvider    = errors.New("syncjob: provider_id required")
	ErrJobMissingCompetition = errors.New("syncjob: competition_id required")
	ErrJobMissingSchedule    = errors.New("syncjob: scheduled_at required")
)

// NewSyncJob constructs a SyncJob with invariants. The Scheduler
// will call this; tests can call it too.
//
// Returns a value (not pointer) — SyncJob is small + immutable once
// scheduled. Retries produce a NEW SyncJob with the same JobID;
// state (running/done/failed) lives in the Scheduler's job ledger,
// not on this contract.
func NewSyncJob(
	id JobID,
	providerID string,
	competitionID uuid.UUID,
	st SyncType,
	priority Priority,
	scheduledAt time.Time,
	metadata map[string]string,
) (SyncJob, error) {
	if providerID == "" {
		return SyncJob{}, ErrJobMissingProvider
	}
	if competitionID == uuid.Nil {
		return SyncJob{}, ErrJobMissingCompetition
	}
	if scheduledAt.IsZero() {
		return SyncJob{}, ErrJobMissingSchedule
	}
	if _, err := ParseSyncType(string(st)); err != nil {
		return SyncJob{}, fmt.Errorf("syncjob: %w", err)
	}
	// Defensive copy of metadata so the caller can mutate after
	// construction without bleeding into the persisted contract.
	var meta map[string]string
	if len(metadata) > 0 {
		meta = make(map[string]string, len(metadata))
		for k, v := range metadata {
			meta[k] = v
		}
	}
	return SyncJob{
		JobID:          id,
		ProviderID:     providerID,
		CompetitionID:  competitionID,
		SyncType:       st,
		Priority:       priority,
		ScheduledAt:    scheduledAt.UTC(),
		Metadata:       meta,
		MaxAttempts:    DefaultMaxAttempts,
		CurrentAttempt: 0,
	}, nil
}

// AttemptsExhausted reports whether the next retry would exceed
// MaxAttempts. The queue adapter consults this before re-enqueueing
// — exhausted jobs route to Fail instead of Retry.
func (j SyncJob) AttemptsExhausted() bool {
	return j.CurrentAttempt >= j.MaxAttempts
}

// PreparedForRetry returns a copy of the job with CurrentAttempt+1
// and RetryAfter stamped from the supplied baseTime + the exponential
// backoff for the new attempt. The queue adapter calls this just
// before re-enqueuing.
func (j SyncJob) PreparedForRetry(baseTime time.Time) SyncJob {
	next := j
	next.CurrentAttempt = j.CurrentAttempt + 1
	next.RetryAfter = baseTime.UTC().Add(NextRetryDelay(next.CurrentAttempt))
	return next
}
