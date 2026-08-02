// Odds operational mode — Sprint 6.1 runtime-configurable World Cup mode.
package application_test

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/application/oddsmode"
)

// flipSource is a mutable mode source for testing runtime flips.
type flipSource struct {
	mu sync.Mutex
	m  oddsmode.Mode
}

func (f *flipSource) set(m oddsmode.Mode) { f.mu.Lock(); f.m = m; f.mu.Unlock() }
func (f *flipSource) Mode(_ context.Context) (oddsmode.Mode, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.m, nil
}

func TestModeParseFailsSafeToNormal(t *testing.T) {
	if oddsmode.Parse("bogus") != oddsmode.ModeNormal {
		t.Error("unknown mode must default to normal")
	}
	if oddsmode.Parse("worldcup") != oddsmode.ModeWorldCup {
		t.Error("worldcup must parse")
	}
}

func TestModeControllerReflectsSource(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	src := &flipSource{m: oddsmode.ModeNormal}
	c := oddsmode.NewController(src, oddsmode.DefaultProfiles(), oddsmode.ModeNormal, 10*time.Second, clk)

	mode, profile := c.Current(context.Background())
	if mode != oddsmode.ModeNormal || profile.PollMultiplier != 1.0 {
		t.Fatalf("expected normal profile, got %v %+v", mode, profile)
	}

	// Operator flips to worldcup at runtime.
	src.set(oddsmode.ModeWorldCup)

	// Within the cache TTL the controller still reports the cached mode.
	if mode, _ := c.Current(context.Background()); mode != oddsmode.ModeNormal {
		t.Errorf("cache should hold previous mode within TTL, got %v", mode)
	}

	// After the TTL elapses, the new mode takes effect — no redeploy.
	clk.Advance(11 * time.Second)
	mode, profile = c.Current(context.Background())
	if mode != oddsmode.ModeWorldCup {
		t.Errorf("expected worldcup after TTL, got %v", mode)
	}
	if profile.PollMultiplier >= 1.0 {
		t.Errorf("worldcup must poll more often (multiplier <1): %v", profile.PollMultiplier)
	}
	if profile.Concurrency <= oddsmode.DefaultProfiles()[oddsmode.ModeNormal].Concurrency {
		t.Error("worldcup must raise concurrency")
	}
}
