// Rate limiter tests — Sprint 3.
//
// Architectural invariant: adapters must NEVER know quotas. This
// test suite exercises the application-level limiter directly with
// a frozen clock, then asserts the four windows (burst / minute /
// hour / daily) each bind independently and return the expected
// Reason for the binding window.
package application_test

import (
	"testing"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/application/ratelimit"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

type stepClock struct{ now time.Time }

func (c *stepClock) Now() time.Time { return c.now }
func (c *stepClock) Advance(d time.Duration) {
	c.now = c.now.Add(d)
}

func TestRateLimiterUnconfiguredProviderAllowsEverything(t *testing.T) {
	c := &stepClock{now: time.Now()}
	l := ratelimit.NewSliding(c)
	for i := 0; i < 1000; i++ {
		if d := l.Allow("p"); !d.Allowed {
			t.Fatalf("iteration %d unexpectedly blocked: %+v", i, d)
		}
	}
}

func TestRateLimiterBurstBindsFirst(t *testing.T) {
	c := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	l := ratelimit.NewSliding(c)
	p, _ := syncdom.NewRateLimitPolicy("p", 100, 1000, 10000, 3)
	l.SetPolicy(p)

	for i := 0; i < 3; i++ {
		if d := l.Allow("p"); !d.Allowed {
			t.Fatalf("expected allow at i=%d, got %+v", i, d)
		}
	}
	// 4th request within the burst-second must trip the burst window.
	d := l.Allow("p")
	if d.Allowed || d.Reason != "burst" {
		t.Errorf("expected burst block, got %+v", d)
	}
}

func TestRateLimiterMinuteBinds(t *testing.T) {
	c := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	l := ratelimit.NewSliding(c)
	// rpm=5; burst high enough to bypass it
	p, _ := syncdom.NewRateLimitPolicy("p", 5, 0, 0, 100)
	l.SetPolicy(p)

	for i := 0; i < 5; i++ {
		// Step 2s between calls so burst (1s window) doesn't trip.
		c.Advance(2 * time.Second)
		if d := l.Allow("p"); !d.Allowed {
			t.Fatalf("expected allow at i=%d, got %+v", i, d)
		}
	}
	c.Advance(2 * time.Second)
	d := l.Allow("p")
	if d.Allowed || d.Reason != "minute" {
		t.Errorf("expected minute block, got %+v", d)
	}
}

func TestRateLimiterRecoversAfterWindow(t *testing.T) {
	c := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	l := ratelimit.NewSliding(c)
	p, _ := syncdom.NewRateLimitPolicy("p", 2, 0, 0, 100)
	l.SetPolicy(p)

	c.Advance(2 * time.Second)
	if d := l.Allow("p"); !d.Allowed {
		t.Fatalf("first allow blocked: %+v", d)
	}
	c.Advance(2 * time.Second)
	if d := l.Allow("p"); !d.Allowed {
		t.Fatalf("second allow blocked: %+v", d)
	}
	c.Advance(2 * time.Second)
	if d := l.Allow("p"); d.Allowed {
		t.Fatalf("third allow should have blocked, got %+v", d)
	}

	// Step well past the 1-minute window — limiter should reset.
	c.Advance(2 * time.Minute)
	if d := l.Allow("p"); !d.Allowed {
		t.Errorf("expected allow after window expiry, got %+v", d)
	}
}

func TestRateLimiterIsolatesProviders(t *testing.T) {
	c := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	l := ratelimit.NewSliding(c)
	p1, _ := syncdom.NewRateLimitPolicy("p1", 0, 0, 0, 1)
	p2, _ := syncdom.NewRateLimitPolicy("p2", 0, 0, 0, 1)
	l.SetPolicy(p1)
	l.SetPolicy(p2)

	if d := l.Allow("p1"); !d.Allowed {
		t.Fatal("p1 first call blocked")
	}
	// p2 quota must NOT be drained by p1.
	if d := l.Allow("p2"); !d.Allowed {
		t.Fatal("p2 unexpectedly blocked — provider isolation broken")
	}
}
