// DynamicPollPolicy — Sprint 6.1.
//
// Kickoff-proximity-aware polling. Fixed PollPolicy intervals waste
// quota (a fixture 10 days out gets polled as often as one kicking off
// in 10 minutes). DynamicPollPolicy maps "time until kickoff" to a
// refresh cadence through an ordered set of windows, with a dedicated
// in-play cadence and a hard stop once a fixture is finished.
//
// Example (the Sprint 6.1 reference policy):
//
//	> 7d        → 12h
//	2d–7d       → 6h
//	< 48h       → 1h
//	< 6h        → 15m
//	live        → 1m
//	finished    → disabled
//
// The type is pure + configurable: the windows, live cadence and the
// far-future default are all caller-supplied. The Scheduler resolves a
// competition's nearest-kickoff proximity (via a schedule source) and
// asks the policy for the effective interval.
package sync

import (
	"errors"
	"sort"
	"time"
)

// PollWindow is one proximity tier: "when the kickoff is at most
// MaxLeadTime away, poll every Interval". Windows are evaluated from
// the tightest MaxLeadTime upward, so the closest matching tier wins.
type PollWindow struct {
	MaxLeadTime time.Duration
	Interval    time.Duration
}

// DynamicPollPolicy is the kickoff-aware cadence for one
// (provider, sync_type).
type DynamicPollPolicy struct {
	ProviderID string
	SyncType   SyncType

	// Windows, sorted ascending by MaxLeadTime at construction.
	Windows []PollWindow

	// LiveInterval is used when a fixture is in-play. Must be > 0 to
	// take effect.
	LiveInterval time.Duration

	// DefaultInterval applies when the nearest kickoff is farther than
	// every window's MaxLeadTime (the "distant future" cadence).
	DefaultInterval time.Duration

	Enabled bool
}

var (
	ErrDynamicMissingProvider = errors.New("dynamicpollpolicy: provider_id required")
	ErrDynamicNoWindows       = errors.New("dynamicpollpolicy: at least one window required")
	ErrDynamicBadInterval     = errors.New("dynamicpollpolicy: intervals must be > 0")
	ErrDynamicDefaultInterval = errors.New("dynamicpollpolicy: default_interval must be > 0")
)

// NewDynamicPollPolicy validates + normalises (sorts windows). The
// windows slice is copied so later caller mutation can't reorder the
// stored policy.
func NewDynamicPollPolicy(
	providerID string,
	st SyncType,
	windows []PollWindow,
	liveInterval time.Duration,
	defaultInterval time.Duration,
	enabled bool,
) (DynamicPollPolicy, error) {
	if providerID == "" {
		return DynamicPollPolicy{}, ErrDynamicMissingProvider
	}
	if _, err := ParseSyncType(string(st)); err != nil {
		return DynamicPollPolicy{}, err
	}
	if len(windows) == 0 {
		return DynamicPollPolicy{}, ErrDynamicNoWindows
	}
	if defaultInterval <= 0 {
		return DynamicPollPolicy{}, ErrDynamicDefaultInterval
	}
	cp := make([]PollWindow, len(windows))
	copy(cp, windows)
	for _, w := range cp {
		if w.MaxLeadTime <= 0 || w.Interval <= 0 {
			return DynamicPollPolicy{}, ErrDynamicBadInterval
		}
	}
	sort.Slice(cp, func(i, j int) bool { return cp[i].MaxLeadTime < cp[j].MaxLeadTime })

	return DynamicPollPolicy{
		ProviderID:      providerID,
		SyncType:        st,
		Windows:         cp,
		LiveInterval:    liveInterval,
		DefaultInterval: defaultInterval,
		Enabled:         enabled,
	}, nil
}

// EffectiveInterval resolves the cadence for a lane.
//
//   - finished == true            → (0, false): no further polling.
//   - live == true + LiveInterval → (LiveInterval, true).
//   - otherwise: the tightest window whose MaxLeadTime covers
//     timeToKickoff; if the kickoff is farther than every window (or
//     unknown, i.e. a negative/sentinel timeToKickoff is treated as
//     "very near" only when live), DefaultInterval is returned.
//
// A negative timeToKickoff (kickoff already passed but not flagged
// finished — e.g. an in-play match the schedule source hasn't marked
// live yet) falls into the tightest window so the lane stays hot
// rather than going cold.
func (p DynamicPollPolicy) EffectiveInterval(
	timeToKickoff time.Duration, live, finished bool,
) (time.Duration, bool) {
	if finished {
		return 0, false
	}
	if live && p.LiveInterval > 0 {
		return p.LiveInterval, true
	}
	if timeToKickoff < 0 {
		// Kickoff passed but not finished — keep it on the tightest tier.
		return p.Windows[0].Interval, true
	}
	for _, w := range p.Windows {
		if timeToKickoff <= w.MaxLeadTime {
			return w.Interval, true
		}
	}
	return p.DefaultInterval, true
}
