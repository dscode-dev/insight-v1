// Package scheduling — Sprint 6.1 dynamic scheduling.
//
// Holds the concrete SchedulingAdvisor (OddsAdvisor) the Planner
// consults, plus the in-memory KickoffTracker that turns observed
// fixture kickoff times into the per-competition proximity signal the
// dynamic poll policy needs.
//
// Feeding: the odds adapter reports every fixture's commence_time via
// the (local) ScheduleObserver seam as a side effect of fetching odds.
// The tracker aggregates those into "nearest upcoming kickoff / any
// live / has upcoming" per competition — no extra provider calls.
package scheduling

import (
	"context"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// MatchProximity is the per-competition aggregate the advisor reasons
// about.
type MatchProximity struct {
	// NearestKickoff is the duration until the soonest upcoming
	// kickoff. Zero/!HasUpcoming means none is known upcoming.
	NearestKickoff time.Duration
	HasUpcoming    bool
	AnyLive        bool
}

// MatchScheduleSource resolves a competition's kickoff proximity.
type MatchScheduleSource interface {
	Proximity(ctx context.Context, competitionID uuid.UUID) (MatchProximity, error)
}

// KickoffTracker is an in-memory MatchScheduleSource fed via
// ObserveKickoff. A fixture is considered "live" from its kickoff
// until kickoff+LiveWindow; entries are pruned once they age past
// kickoff+RetainAfter.
type KickoffTracker struct {
	clock       ports.Clock
	liveWindow  time.Duration
	retainAfter time.Duration

	mu     sync.Mutex
	byComp map[uuid.UUID]map[string]time.Time
}

// NewKickoffTracker builds a tracker. Sensible defaults: a match is
// live for 3h after kickoff and retained for 6h after kickoff.
func NewKickoffTracker(clock ports.Clock, liveWindow, retainAfter time.Duration) *KickoffTracker {
	if liveWindow <= 0 {
		liveWindow = 3 * time.Hour
	}
	if retainAfter <= 0 {
		retainAfter = 6 * time.Hour
	}
	return &KickoffTracker{
		clock:       clock,
		liveWindow:  liveWindow,
		retainAfter: retainAfter,
		byComp:      map[uuid.UUID]map[string]time.Time{},
	}
}

// ObserveKickoff records (or updates) a fixture's kickoff time. Matches
// the adapter's ScheduleObserver seam.
func (t *KickoffTracker) ObserveKickoff(
	_ context.Context, competitionID uuid.UUID, matchKey string, kickoff time.Time,
) {
	if competitionID == uuid.Nil || matchKey == "" || kickoff.IsZero() {
		return
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	m, ok := t.byComp[competitionID]
	if !ok {
		m = map[string]time.Time{}
		t.byComp[competitionID] = m
	}
	m[matchKey] = kickoff.UTC()
}

// Proximity computes the aggregate for one competition, pruning stale
// fixtures as it scans.
func (t *KickoffTracker) Proximity(_ context.Context, competitionID uuid.UUID) (MatchProximity, error) {
	now := t.clock.Now().UTC()
	t.mu.Lock()
	defer t.mu.Unlock()

	matches, ok := t.byComp[competitionID]
	if !ok {
		return MatchProximity{}, nil
	}

	var (
		nearest     time.Duration
		hasUpcoming bool
		anyLive     bool
	)
	for key, kickoff := range matches {
		age := now.Sub(kickoff)
		// Prune fixtures well past their live window.
		if age > t.retainAfter {
			delete(matches, key)
			continue
		}
		if age >= 0 && age <= t.liveWindow {
			anyLive = true
			continue
		}
		if kickoff.After(now) {
			ttk := kickoff.Sub(now)
			if !hasUpcoming || ttk < nearest {
				nearest = ttk
				hasUpcoming = true
			}
		}
	}
	if len(matches) == 0 {
		delete(t.byComp, competitionID)
	}
	return MatchProximity{
		NearestKickoff: nearest,
		HasUpcoming:    hasUpcoming,
		AnyLive:        anyLive,
	}, nil
}
