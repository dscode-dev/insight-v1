// Package budget — Sprint 6.1 quota budget manager.
//
// Provider quotas are a hard, money-shaped constraint (e.g. The Odds
// API free tier: 500 requests/month). The rate limiter smooths burst
// pressure over short windows; the budget manager protects the LONG
// windows (hour/day/month) and makes scheduling budget-aware.
//
// Two responsibilities:
//
//   - Record(provider): the runner reports every real provider request
//     so the long-window counters stay accurate across restarts (the
//     production store is Redis-backed).
//   - Allow(provider, priority) + Pressure(provider): the scheduler
//     consults these to (a) hard-skip low-priority lanes once budget is
//     tight and (b) stretch poll intervals as pressure rises.
//
// Priority order (Sprint 6.1 spec): live > within-24h > within-72h >
// distant. As pressure climbs the manager progressively refuses the
// lower tiers — "never waste budget on distant fixtures while live
// events exist".
//
// The store is an interface so the same logic runs against an
// in-memory map (single instance / tests) or Redis (production,
// multi-instance, survives restarts).
package budget

import (
	"context"
	"fmt"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// Priority ranks a scheduling lane. Lower value = more important.
type Priority int

const (
	PriorityLive      Priority = iota // in-play
	PriorityWithin24h                 // kickoff < 24h
	PriorityWithin72h                 // kickoff < 72h
	PriorityFuture                    // everything farther out
)

func (p Priority) String() string {
	switch p {
	case PriorityLive:
		return "live"
	case PriorityWithin24h:
		return "within_24h"
	case PriorityWithin72h:
		return "within_72h"
	default:
		return "future"
	}
}

// Caps holds the per-window request ceilings. Zero means "no cap" for
// that window.
type Caps struct {
	Hourly  int
	Daily   int
	Monthly int
}

// CounterStore persists rolling counters keyed by an opaque string.
// Increment bumps the counter and returns the new value; the TTL keeps
// expired windows from leaking. Count reads without mutating.
type CounterStore interface {
	Increment(ctx context.Context, key string, ttl time.Duration) (int64, error)
	Count(ctx context.Context, key string) (int64, error)
}

// Decision is the budget verdict for a prospective request.
type Decision struct {
	Allowed bool
	// IntervalScale multiplies the lane's base poll interval. 1.0 at
	// low pressure; grows as the budget tightens so distant lanes back
	// off automatically.
	IntervalScale float64
	Reason        string
}

// Manager is the budget-aware scheduler advisor + request accountant.
type Manager struct {
	provider string
	caps     Caps
	store    CounterStore
	clock    ports.Clock
}

func NewManager(provider string, caps Caps, store CounterStore, clock ports.Clock) *Manager {
	return &Manager{provider: provider, caps: caps, store: store, clock: clock}
}

// Provider is the source this manager accounts for.
func (m *Manager) Provider() string { return m.provider }

func (m *Manager) keys(now time.Time) (hourly, daily, monthly string) {
	hourly = fmt.Sprintf("budget:%s:h:%s", m.provider, now.UTC().Format("2006010215"))
	daily = fmt.Sprintf("budget:%s:d:%s", m.provider, now.UTC().Format("20060102"))
	monthly = fmt.Sprintf("budget:%s:m:%s", m.provider, now.UTC().Format("200601"))
	return
}

// Record accounts one real provider request across all windows. Called
// by the runner AFTER a fetch is dispatched (not on a cache hit).
func (m *Manager) Record(ctx context.Context) error {
	now := m.clock.Now()
	h, d, mo := m.keys(now)
	if _, err := m.store.Increment(ctx, h, 2*time.Hour); err != nil {
		return err
	}
	if _, err := m.store.Increment(ctx, d, 48*time.Hour); err != nil {
		return err
	}
	if _, err := m.store.Increment(ctx, mo, 62*24*time.Hour); err != nil {
		return err
	}
	return nil
}

// Pressure returns the budget pressure in [0,1+]: the most-binding
// window's consumed fraction. >= 1.0 means a window cap is reached.
func (m *Manager) Pressure(ctx context.Context) (float64, error) {
	now := m.clock.Now()
	h, d, mo := m.keys(now)
	pressure := 0.0
	for _, w := range []struct {
		key string
		cap int
	}{{h, m.caps.Hourly}, {d, m.caps.Daily}, {mo, m.caps.Monthly}} {
		if w.cap <= 0 {
			continue
		}
		count, err := m.store.Count(ctx, w.key)
		if err != nil {
			return 0, err
		}
		if ratio := float64(count) / float64(w.cap); ratio > pressure {
			pressure = ratio
		}
	}
	return pressure, nil
}

// Allow decides whether a lane at the given priority should be polled
// now, and how much to stretch its interval. Pure pressure→policy
// mapping once Pressure is read.
func (m *Manager) Allow(ctx context.Context, priority Priority) (Decision, error) {
	pressure, err := m.Pressure(ctx)
	if err != nil {
		return Decision{}, err
	}
	return decide(pressure, priority), nil
}

// decide is the pure pressure→decision policy, factored out for
// exhaustive unit testing.
//
// Tiers (the minimum priority still served at each pressure band):
//
//	pressure < 0.5    → serve all,           1.0× interval
//	0.5 ≤ p < 0.75    → drop Future,         1.5× interval
//	0.75 ≤ p < 0.9    → ≤ Within72h,         2.0× interval
//	0.9 ≤ p < 1.0     → ≤ Within24h,         3.0× interval
//	p ≥ 1.0           → Live only,           4.0× interval
func decide(pressure float64, priority Priority) Decision {
	switch {
	case pressure < 0.5:
		return Decision{Allowed: true, IntervalScale: 1.0}
	case pressure < 0.75:
		return Decision{
			Allowed:       priority <= PriorityWithin72h,
			IntervalScale: 1.5,
			Reason:        reasonIfBlocked(priority <= PriorityWithin72h, "budget_pressure_moderate"),
		}
	case pressure < 0.9:
		return Decision{
			Allowed:       priority <= PriorityWithin72h,
			IntervalScale: 2.0,
			Reason:        reasonIfBlocked(priority <= PriorityWithin72h, "budget_pressure_high"),
		}
	case pressure < 1.0:
		return Decision{
			Allowed:       priority <= PriorityWithin24h,
			IntervalScale: 3.0,
			Reason:        reasonIfBlocked(priority <= PriorityWithin24h, "budget_pressure_critical"),
		}
	default:
		return Decision{
			Allowed:       priority == PriorityLive,
			IntervalScale: 4.0,
			Reason:        reasonIfBlocked(priority == PriorityLive, "budget_exhausted"),
		}
	}
}

func reasonIfBlocked(allowed bool, reason string) string {
	if allowed {
		return ""
	}
	return reason
}
