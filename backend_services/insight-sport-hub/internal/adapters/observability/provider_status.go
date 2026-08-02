// Provider status tracker — Sprint 2.
//
// In-memory, lock-protected store of per-provider operational state.
// Adapters call Record* from a single decorator at the edge of every
// HTTP call; the public Snapshot() reads the latest values.
//
// Stateless adapters route through this tracker via the
// observability port — keeps the adapter itself free of mutable
// state (architectural rule "adapters MUST be stateless").
//
// Sprint 2 ships in-memory only. Sprint 3+ may persist to Postgres
// for cross-pod aggregation; the interface stays the same.
package observability

import (
	"sync"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// ProviderStatusRecorder is what adapters use to log call outcomes.
// Defined locally rather than in ports/ because no application
// service depends on it — only the HTTP /providers/status route +
// the adapter decorator.
//
// Sprint 2.1 adds RegisterProfile so the boot composition root can
// stamp the static metadata once. Adapters never call it — the
// composition root does, from data the adapter exposes via
// `Identity()` + future config tables.
type ProviderStatusRecorder interface {
	RecordSuccess(sourceID string, latency time.Duration)
	RecordFailure(sourceID string, latency time.Duration, err error)
	RegisterProfile(sourceID string, p Profile)
	Snapshot(sourceID string) ports.HealthSnapshot
	All() map[string]ports.HealthSnapshot

	// Sprint 3 — scheduler/runner lifecycle counters. The dispatcher
	// and the runner mutate these; the HTTP status endpoint exposes
	// the result.
	IncQueued(sourceID string)
	IncQueueDropped(sourceID string, reason string)
	IncStarted(sourceID string)
	IncCompleted(sourceID string, latency time.Duration)
	IncFailed(sourceID string, latency time.Duration, reason string)
	IncRateLimitBlocked(sourceID string, reason string)
	SetNextScheduled(sourceID string, at time.Time)
}

// Profile is the static metadata the boot path registers per source.
// Read-only after registration. The HTTP /providers/status route
// merges these fields into every snapshot.
type Profile struct {
	Capabilities source.ProviderCapability
	RatePolicy   syncdom.RateLimitPolicy
	PollPolicies []syncdom.PollPolicy
}

// ProviderStatus is the default in-memory implementation. Thread-
// safe via a single RWMutex (per-provider locks would optimise
// concurrent-distinct-provider writes; deferred until contention is
// observed).
type ProviderStatus struct {
	mu      sync.RWMutex
	entries map[string]*entry
}

type entry struct {
	reachable           bool
	lastSuccessfulSync  time.Time
	lastFailure         time.Time
	lastError           string
	totalLatency        time.Duration
	requestsTotal       int64
	requestsFailedTotal int64

	// Sprint 2.1 static profile. Populated once at boot via
	// RegisterProfile; never mutated by Record* calls.
	profile Profile

	// Sprint 3 — scheduler/runner lifecycle counters.
	queuedJobs        int64
	runningJobs       int64
	completedJobs     int64
	failedJobs        int64
	queueDropped      int64
	rateLimitBlocked  int64
	lastExecution     time.Time
	nextScheduledExec time.Time
}

func NewProviderStatus() *ProviderStatus {
	return &ProviderStatus{entries: map[string]*entry{}}
}

func (s *ProviderStatus) get(sourceID string) *entry {
	e, ok := s.entries[sourceID]
	if !ok {
		e = &entry{}
		s.entries[sourceID] = e
	}
	return e
}

func (s *ProviderStatus) RecordSuccess(sourceID string, latency time.Duration) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := s.get(sourceID)
	e.reachable = true
	e.lastSuccessfulSync = time.Now().UTC()
	e.totalLatency += latency
	e.requestsTotal++
}

// RegisterProfile is called once per source at composition time. Safe
// to call again with the same payload (idempotent overwrite — last
// writer wins; no diff semantics needed because this is config, not
// state).
func (s *ProviderStatus) RegisterProfile(sourceID string, p Profile) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := s.get(sourceID)
	e.profile = p
}

func (s *ProviderStatus) RecordFailure(sourceID string, latency time.Duration, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := s.get(sourceID)
	e.reachable = false
	e.lastFailure = time.Now().UTC()
	if err != nil {
		// Single-line summary — NEVER include API keys or full URLs.
		// The decorator constructs a sanitised error before calling.
		e.lastError = truncate(err.Error(), 256)
	}
	e.totalLatency += latency
	e.requestsTotal++
	e.requestsFailedTotal++
}

// ---------------------------------------------------------------------------
// Sprint 3 lifecycle counters
// ---------------------------------------------------------------------------

// IncQueued — the dispatcher successfully enqueued a job.
func (s *ProviderStatus) IncQueued(sourceID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.get(sourceID).queuedJobs++
}

// IncQueueDropped — the dispatcher could NOT enqueue (full/closed/error).
// Reason is currently stored only via the latest-error path of logging;
// the counter is aggregate. A future per-reason histogram lives in
// Prometheus, not here.
func (s *ProviderStatus) IncQueueDropped(sourceID string, _ string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.get(sourceID).queueDropped++
}

// IncStarted — a worker pulled the job off the queue and is about to
// execute. Transitions one queued slot into one running slot.
func (s *ProviderStatus) IncStarted(sourceID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := s.get(sourceID)
	if e.queuedJobs > 0 {
		e.queuedJobs--
	}
	e.runningJobs++
}

// IncCompleted — the job finished successfully.
func (s *ProviderStatus) IncCompleted(sourceID string, latency time.Duration) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := s.get(sourceID)
	if e.runningJobs > 0 {
		e.runningJobs--
	}
	e.completedJobs++
	e.lastExecution = time.Now().UTC()
	_ = latency // reserved for a future per-job-latency average
}

// IncFailed — the job ended in failure (any reason: rate limit,
// adapter error, ingest error).
func (s *ProviderStatus) IncFailed(sourceID string, latency time.Duration, reason string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := s.get(sourceID)
	if e.runningJobs > 0 {
		e.runningJobs--
	}
	e.failedJobs++
	e.lastExecution = time.Now().UTC()
	if reason != "" {
		e.lastError = truncate(reason, 256)
	}
	_ = latency
}

// IncRateLimitBlocked — the limiter denied a request.
func (s *ProviderStatus) IncRateLimitBlocked(sourceID string, _ string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.get(sourceID).rateLimitBlocked++
}

// SetNextScheduled — the planner just decided when the next lane for
// this provider should fire. The status endpoint surfaces this so the
// admin UI can render a countdown.
func (s *ProviderStatus) SetNextScheduled(sourceID string, at time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.get(sourceID).nextScheduledExec = at.UTC()
}

func (s *ProviderStatus) Snapshot(sourceID string) ports.HealthSnapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()
	e, ok := s.entries[sourceID]
	if !ok {
		return ports.HealthSnapshot{SourceID: sourceID}
	}
	return toSnapshot(sourceID, e)
}

func (s *ProviderStatus) All() map[string]ports.HealthSnapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make(map[string]ports.HealthSnapshot, len(s.entries))
	for id, e := range s.entries {
		out[id] = toSnapshot(id, e)
	}
	return out
}

func toSnapshot(sourceID string, e *entry) ports.HealthSnapshot {
	var avg int64
	if e.requestsTotal > 0 {
		avg = e.totalLatency.Milliseconds() / e.requestsTotal
	}
	return ports.HealthSnapshot{
		SourceID:               sourceID,
		Reachable:              e.reachable,
		LastSuccessfulSync:     e.lastSuccessfulSync,
		LastFailure:            e.lastFailure,
		LastError:              e.lastError,
		AverageLatencyMs:       avg,
		RequestsTotal:          e.requestsTotal,
		RequestsFailedTotal:    e.requestsFailedTotal,
		Capabilities:           e.profile.Capabilities,
		RatePolicy:             e.profile.RatePolicy,
		PollPolicies:           e.profile.PollPolicies,
		QueuedJobs:             e.queuedJobs,
		RunningJobs:            e.runningJobs,
		CompletedJobs:          e.completedJobs,
		FailedJobs:             e.failedJobs,
		QueueDroppedTotal:      e.queueDropped,
		RateLimitBlockedTotal:  e.rateLimitBlocked,
		LastExecution:          e.lastExecution,
		NextScheduledExecution: e.nextScheduledExec,
	}
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
