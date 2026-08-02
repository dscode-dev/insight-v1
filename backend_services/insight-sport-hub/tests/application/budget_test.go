// Budget manager — Sprint 6.1 quota pressure + priority gating.
package application_test

import (
	"context"
	"testing"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/application/budget"
)

func recordN(t *testing.T, m *budget.Manager, n int) {
	t.Helper()
	for i := 0; i < n; i++ {
		if err := m.Record(context.Background()); err != nil {
			t.Fatalf("record: %v", err)
		}
	}
}

func newBudget(monthly int, clk *stepClock) *budget.Manager {
	store := budget.NewMemoryStore(clk.Now)
	return budget.NewManager("the_odds_api", budget.Caps{Monthly: monthly}, store, clk)
}

func TestBudgetNoPressureAllowsAll(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	m := newBudget(10, clk)
	for _, p := range []budget.Priority{
		budget.PriorityLive, budget.PriorityWithin24h,
		budget.PriorityWithin72h, budget.PriorityFuture,
	} {
		d, err := m.Allow(context.Background(), p)
		if err != nil {
			t.Fatal(err)
		}
		if !d.Allowed || d.IntervalScale != 1.0 {
			t.Errorf("priority %v at zero pressure: %+v", p, d)
		}
	}
}

func TestBudgetModeratePressureDropsFuture(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	m := newBudget(10, clk)
	recordN(t, m, 6) // 0.6 pressure

	future, _ := m.Allow(context.Background(), budget.PriorityFuture)
	if future.Allowed {
		t.Error("distant fixtures must be dropped at 0.6 pressure")
	}
	near, _ := m.Allow(context.Background(), budget.PriorityWithin72h)
	if !near.Allowed {
		t.Error("within-72h must still be served at 0.6 pressure")
	}
	if near.IntervalScale <= 1.0 {
		t.Error("interval should stretch under pressure")
	}
}

func TestBudgetCriticalKeepsOnly24hAndLive(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	m := newBudget(10, clk)
	recordN(t, m, 9) // 0.9 pressure → critical band

	if d, _ := m.Allow(context.Background(), budget.PriorityWithin72h); d.Allowed {
		t.Error("72h must be dropped at 0.9 pressure")
	}
	if d, _ := m.Allow(context.Background(), budget.PriorityWithin24h); !d.Allowed {
		t.Error("24h must survive at 0.9 pressure")
	}
}

func TestBudgetExhaustedKeepsOnlyLive(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	m := newBudget(10, clk)
	recordN(t, m, 10) // 1.0 — cap reached

	if d, _ := m.Allow(context.Background(), budget.PriorityWithin24h); d.Allowed {
		t.Error("only live survives once the cap is reached")
	}
	live, _ := m.Allow(context.Background(), budget.PriorityLive)
	if !live.Allowed {
		t.Error("live must always be served")
	}
}

func TestBudgetMonthlyWindowRollsOver(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 30, 23, 0, 0, 0, time.UTC)}
	m := newBudget(10, clk)
	recordN(t, m, 10) // June exhausted

	if d, _ := m.Allow(context.Background(), budget.PriorityFuture); d.Allowed {
		t.Error("June should be exhausted")
	}
	// Roll into July — a fresh monthly window.
	clk.Advance(2 * time.Hour)
	if d, _ := m.Allow(context.Background(), budget.PriorityFuture); !d.Allowed {
		t.Error("new month must reset budget pressure")
	}
}
