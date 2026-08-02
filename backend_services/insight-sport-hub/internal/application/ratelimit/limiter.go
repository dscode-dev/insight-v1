// Package ratelimit — Sprint 3.
//
// Application-level rate enforcement. The Scheduler/Runner consult
// the limiter BEFORE invoking an adapter; adapters NEVER know their
// own quotas. This boundary is the architectural rule:
//
//	Scheduler decides WHEN.
//	RateLimiter decides IF.
//	Adapter decides HOW to fetch.
//
// Implementation: per-provider sliding-window counters across four
// axes (per-second burst, per-minute, per-hour, per-day). A request
// is allowed iff EVERY configured window still has headroom — the
// most-binding axis dictates the answer.
//
// In-memory backing today; the interface is shaped so a Redis-based
// distributed limiter (Sprint 4+) can drop in without callers
// changing.
package ratelimit

import (
	"sync"
	"time"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// Limiter is the consumer-facing interface. Allow records the
// request atomically when it returns true — callers MUST NOT call
// Allow and then skip the request, or quota accounting drifts.
type Limiter interface {
	Allow(providerID string) Decision
	SetPolicy(p syncdom.RateLimitPolicy)
}

// Decision is the typed result of Allow. Allowed=false means the
// request must NOT proceed; Reason explains which window blocked,
// surfaced in logs + the future admin UI.
type Decision struct {
	Allowed bool
	Reason  string // "burst" | "minute" | "hour" | "daily" | ""
}

// SlidingLimiter is the default in-memory implementation.
//
// Concurrency: a single RWMutex protects both policies and history.
// At small fan-out (one tick per scheduler interval, one Allow per
// dispatched job) this is the right trade — finer-grained per-
// provider locks would optimise distinct-provider contention but
// complicate Set/Clear semantics.
type SlidingLimiter struct {
	mu       sync.Mutex
	policies map[string]syncdom.RateLimitPolicy
	history  map[string][]time.Time
	clock    ports.Clock
}

// NewSliding constructs a limiter. The clock is injected so tests
// can drive time deterministically.
func NewSliding(clock ports.Clock) *SlidingLimiter {
	return &SlidingLimiter{
		policies: map[string]syncdom.RateLimitPolicy{},
		history:  map[string][]time.Time{},
		clock:    clock,
	}
}

// SetPolicy registers (or overwrites) the policy for a provider.
// Calling with a zero-value policy is allowed and means "unlimited".
func (l *SlidingLimiter) SetPolicy(p syncdom.RateLimitPolicy) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.policies[p.ProviderID] = p
}

// Allow consults every configured window and either allows + records
// the request, or returns the binding window's name. Order checked:
// burst → minute → hour → daily. The order matches the typical
// failure mode (burst trips first when the scheduler emits a tight
// batch).
func (l *SlidingLimiter) Allow(providerID string) Decision {
	l.mu.Lock()
	defer l.mu.Unlock()

	now := l.clock.Now()
	p, ok := l.policies[providerID]
	if !ok || p.IsUnlimited() {
		l.recordLocked(providerID, now)
		return Decision{Allowed: true}
	}

	times := l.pruneLocked(providerID, now)

	if p.BurstLimit > 0 && countSince(times, now.Add(-time.Second)) >= p.BurstLimit {
		return Decision{Reason: "burst"}
	}
	if p.RequestsPerMinute > 0 && countSince(times, now.Add(-time.Minute)) >= p.RequestsPerMinute {
		return Decision{Reason: "minute"}
	}
	if p.RequestsPerHour > 0 && countSince(times, now.Add(-time.Hour)) >= p.RequestsPerHour {
		return Decision{Reason: "hour"}
	}
	if p.DailyLimit > 0 && countSince(times, now.Add(-24*time.Hour)) >= p.DailyLimit {
		return Decision{Reason: "daily"}
	}

	l.recordLocked(providerID, now)
	return Decision{Allowed: true}
}

// recordLocked appends a request timestamp. Caller holds l.mu.
func (l *SlidingLimiter) recordLocked(providerID string, now time.Time) {
	l.history[providerID] = append(l.history[providerID], now)
}

// pruneLocked drops timestamps older than 24h (the largest window
// configurable). Keeps memory bounded under sustained load.
// Returns the post-prune slice for the caller's convenience.
func (l *SlidingLimiter) pruneLocked(providerID string, now time.Time) []time.Time {
	cutoff := now.Add(-24 * time.Hour)
	times := l.history[providerID]
	idx := 0
	for idx < len(times) && times[idx].Before(cutoff) {
		idx++
	}
	if idx > 0 {
		times = times[idx:]
		l.history[providerID] = times
	}
	return times
}

// countSince counts timestamps within [from, now]. The slice is
// sorted ascending (insertion order = time order) so we scan from
// the end — typical window sizes (a minute, an hour) put the
// boundary well inside the recent tail.
func countSince(times []time.Time, from time.Time) int {
	count := 0
	for i := len(times) - 1; i >= 0; i-- {
		if times[i].Before(from) {
			break
		}
		count++
	}
	return count
}
