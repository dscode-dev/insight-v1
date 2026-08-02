// PollPolicy — Sprint 2.1 contract.
//
// Per-(provider, sync_type) refresh cadence. CONTRACT ONLY —
// Sprint 2.1 does not consume the value. The Scheduler (Sprint 3)
// reads PollPolicy rows to decide when to enqueue the next SyncJob.
//
// LiveInterval coexists with Interval to express the common pattern
// where one data class accelerates during a live window — e.g.
// API-Football results normally poll every 15 minutes but tighten to
// every 15 seconds while a tracked fixture is in progress.
package sync

import (
	"errors"
	"fmt"
	"time"
)

// PollPolicy declares one provider+sync_type's cadence.
type PollPolicy struct {
	ProviderID   string // matches Source.SourceID slug
	SyncType     SyncType
	Interval     time.Duration // baseline cadence
	LiveInterval time.Duration // optional accelerated cadence; 0 == unused
	Enabled      bool
}

var (
	ErrPollPolicyMissingProvider = errors.New("pollpolicy: provider_id required")
	ErrPollPolicyMissingInterval = errors.New("pollpolicy: interval must be > 0")
	ErrPollPolicyInvalidLive     = errors.New("pollpolicy: live_interval must be < interval when set")
)

// NewPollPolicy validates invariants. Enabled defaults to true at
// construction; the Scheduler can toggle later.
func NewPollPolicy(
	providerID string,
	st SyncType,
	interval time.Duration,
	liveInterval time.Duration,
	enabled bool,
) (PollPolicy, error) {
	if providerID == "" {
		return PollPolicy{}, ErrPollPolicyMissingProvider
	}
	if interval <= 0 {
		return PollPolicy{}, ErrPollPolicyMissingInterval
	}
	if _, err := ParseSyncType(string(st)); err != nil {
		return PollPolicy{}, fmt.Errorf("pollpolicy: %w", err)
	}
	// Live cadence, when set, MUST be tighter than baseline — else
	// the field is meaningless or wrong.
	if liveInterval > 0 && liveInterval >= interval {
		return PollPolicy{}, ErrPollPolicyInvalidLive
	}
	return PollPolicy{
		ProviderID:   providerID,
		SyncType:     st,
		Interval:     interval,
		LiveInterval: liveInterval,
		Enabled:      enabled,
	}, nil
}

// EffectiveInterval returns LiveInterval when `live` is true and set;
// otherwise the baseline Interval. The Scheduler calls this with a
// per-competition "any live fixture" signal.
func (p PollPolicy) EffectiveInterval(live bool) time.Duration {
	if live && p.LiveInterval > 0 {
		return p.LiveInterval
	}
	return p.Interval
}
