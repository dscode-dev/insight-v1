// DynamicPollPolicy contract — Sprint 6.1 kickoff-proximity polling.
package domain_test

import (
	"testing"
	"time"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

func refPolicy(t *testing.T) syncdom.DynamicPollPolicy {
	t.Helper()
	p, err := syncdom.NewDynamicPollPolicy(
		"the_odds_api", syncdom.TypeOdds,
		[]syncdom.PollWindow{
			// Intentionally unsorted to exercise normalisation.
			{MaxLeadTime: 7 * 24 * time.Hour, Interval: 6 * time.Hour},
			{MaxLeadTime: 6 * time.Hour, Interval: 15 * time.Minute},
			{MaxLeadTime: 48 * time.Hour, Interval: time.Hour},
		},
		time.Minute,  // live
		12*time.Hour, // default (> 7d)
		true,
	)
	if err != nil {
		t.Fatalf("build policy: %v", err)
	}
	return p
}

func TestDynamicPollPolicyTiers(t *testing.T) {
	p := refPolicy(t)
	cases := []struct {
		name string
		ttk  time.Duration
		want time.Duration
	}{
		{"far_future_10d", 10 * 24 * time.Hour, 12 * time.Hour},
		{"within_7d", 5 * 24 * time.Hour, 6 * time.Hour},
		{"within_48h", 24 * time.Hour, time.Hour},
		{"within_6h", 3 * time.Hour, 15 * time.Minute},
		{"boundary_exactly_6h", 6 * time.Hour, 15 * time.Minute},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, enabled := p.EffectiveInterval(c.ttk, false, false)
			if !enabled {
				t.Fatalf("expected enabled")
			}
			if got != c.want {
				t.Errorf("ttk=%v: got %v, want %v", c.ttk, got, c.want)
			}
		})
	}
}

func TestDynamicPollPolicyLiveWins(t *testing.T) {
	p := refPolicy(t)
	got, enabled := p.EffectiveInterval(10*24*time.Hour, true, false)
	if !enabled || got != time.Minute {
		t.Errorf("live should poll every minute regardless of kickoff: got %v enabled=%v", got, enabled)
	}
}

func TestDynamicPollPolicyFinishedDisabled(t *testing.T) {
	p := refPolicy(t)
	_, enabled := p.EffectiveInterval(time.Hour, false, true)
	if enabled {
		t.Error("finished fixtures must be disabled")
	}
}

func TestDynamicPollPolicyKickoffPassedStaysHot(t *testing.T) {
	p := refPolicy(t)
	// Negative ttk (kickoff passed, not flagged finished/live) → tightest tier.
	got, enabled := p.EffectiveInterval(-5*time.Minute, false, false)
	if !enabled || got != 15*time.Minute {
		t.Errorf("passed-kickoff should use tightest window: got %v enabled=%v", got, enabled)
	}
}

func TestDynamicPollPolicyValidation(t *testing.T) {
	if _, err := syncdom.NewDynamicPollPolicy("", syncdom.TypeOdds, []syncdom.PollWindow{{MaxLeadTime: time.Hour, Interval: time.Minute}}, 0, time.Hour, true); err == nil {
		t.Error("empty provider must error")
	}
	if _, err := syncdom.NewDynamicPollPolicy("p", syncdom.TypeOdds, nil, 0, time.Hour, true); err == nil {
		t.Error("no windows must error")
	}
	if _, err := syncdom.NewDynamicPollPolicy("p", syncdom.TypeOdds, []syncdom.PollWindow{{MaxLeadTime: time.Hour, Interval: time.Minute}}, 0, 0, true); err == nil {
		t.Error("zero default interval must error")
	}
}
