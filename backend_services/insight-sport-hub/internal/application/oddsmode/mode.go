// Package oddsmode — Sprint 6.1 operational mode.
//
// The odds pipeline runs in one of a few operational modes that tune
// aggressiveness without a redeploy. "normal" is the default
// steady-state; "worldcup" turns everything up for tournament windows
// (tighter polling, more concurrency, more monitored matches).
//
// Runtime-configurable: the Controller reads the active mode from a
// Source on every query (the production Source is a Redis key an
// operator flips with a single SET; tests use a Static source). The
// Source is cached for a short TTL so a hot scheduler loop doesn't
// hammer the backing store.
package oddsmode

import (
	"context"
	"sync"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// Mode is the operational mode slug.
type Mode string

const (
	ModeNormal   Mode = "normal"
	ModeWorldCup Mode = "worldcup"
)

// Parse normalises an inbound string, defaulting unknown values to
// normal (fail-safe — an operator typo never accidentally turns the
// pipeline up).
func Parse(s string) Mode {
	switch Mode(s) {
	case ModeWorldCup:
		return ModeWorldCup
	default:
		return ModeNormal
	}
}

// Profile is the per-mode tuning envelope.
type Profile struct {
	// PollMultiplier scales poll intervals. < 1.0 polls MORE often.
	// normal = 1.0, worldcup = 0.5 (twice as frequent).
	PollMultiplier float64
	// Concurrency is the desired worker concurrency for odds fetches.
	Concurrency int
	// MaxMonitoredMatches caps how many fixtures the pipeline tracks.
	MaxMonitoredMatches int
}

// DefaultProfiles returns the built-in tuning for each mode. The
// composition root may override via config.
func DefaultProfiles() map[Mode]Profile {
	return map[Mode]Profile{
		ModeNormal:   {PollMultiplier: 1.0, Concurrency: 4, MaxMonitoredMatches: 200},
		ModeWorldCup: {PollMultiplier: 0.5, Concurrency: 12, MaxMonitoredMatches: 1000},
	}
}

// Source resolves the currently-active mode. Implementations: Static
// (tests / no-Redis) and the Redis-backed source in redisinfra.
type Source interface {
	Mode(ctx context.Context) (Mode, error)
}

// StaticSource always returns the same mode. Used for tests and
// single-instance deployments without runtime mode flipping.
type StaticSource struct{ M Mode }

func (s StaticSource) Mode(_ context.Context) (Mode, error) { return Parse(string(s.M)), nil }

// Controller resolves mode + profile with a short cache so a tight
// scheduler loop doesn't query the backing store every tick.
type Controller struct {
	source   Source
	profiles map[Mode]Profile
	fallback Mode
	cacheTTL time.Duration
	clock    ports.Clock

	mu       sync.Mutex
	cached   Mode
	cachedAt time.Time
	primed   bool
}

func NewController(
	source Source,
	profiles map[Mode]Profile,
	fallback Mode,
	cacheTTL time.Duration,
	clock ports.Clock,
) *Controller {
	if len(profiles) == 0 {
		profiles = DefaultProfiles()
	}
	if cacheTTL <= 0 {
		cacheTTL = 10 * time.Second
	}
	return &Controller{
		source:   source,
		profiles: profiles,
		fallback: Parse(string(fallback)),
		cacheTTL: cacheTTL,
		clock:    clock,
	}
}

// Current returns the active mode + its profile. On a source error it
// returns the last-known mode (or the fallback before the first
// successful read) so a transient backing-store blip never stalls the
// scheduler.
func (c *Controller) Current(ctx context.Context) (Mode, Profile) {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := c.clock.Now()
	if c.primed && now.Sub(c.cachedAt) < c.cacheTTL {
		return c.cached, c.profileFor(c.cached)
	}

	m, err := c.source.Mode(ctx)
	if err != nil {
		if c.primed {
			return c.cached, c.profileFor(c.cached)
		}
		return c.fallback, c.profileFor(c.fallback)
	}
	c.cached = m
	c.cachedAt = now
	c.primed = true
	return m, c.profileFor(m)
}

func (c *Controller) profileFor(m Mode) Profile {
	if p, ok := c.profiles[m]; ok {
		return p
	}
	return c.profiles[ModeNormal]
}
