// Dynamic scheduling — Sprint 6.1 kickoff tracker + odds advisor.
package application_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-sports-hub/internal/application/budget"
	"github.com/konoha-labs/insight-sports-hub/internal/application/oddsmode"
	"github.com/konoha-labs/insight-sports-hub/internal/application/scheduler"
	"github.com/konoha-labs/insight-sports-hub/internal/application/scheduling"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

var schedComp = uuid.MustParse("33333333-3333-4333-8333-333333333333")

func TestKickoffTrackerProximity(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	tr := scheduling.NewKickoffTracker(clk, 3*time.Hour, 6*time.Hour)
	ctx := context.Background()

	tr.ObserveKickoff(ctx, schedComp, "m1", clk.now.Add(30*time.Hour))
	tr.ObserveKickoff(ctx, schedComp, "m2", clk.now.Add(4*time.Hour))

	prox, err := tr.Proximity(ctx, schedComp)
	if err != nil {
		t.Fatal(err)
	}
	if !prox.HasUpcoming || prox.AnyLive {
		t.Fatalf("expected upcoming, no live: %+v", prox)
	}
	if prox.NearestKickoff != 4*time.Hour {
		t.Errorf("nearest should be 4h, got %v", prox.NearestKickoff)
	}

	// A match that kicked off 1h ago is live.
	tr.ObserveKickoff(ctx, schedComp, "m3", clk.now.Add(-1*time.Hour))
	prox, _ = tr.Proximity(ctx, schedComp)
	if !prox.AnyLive {
		t.Error("a recently-started match must register as live")
	}
}

func TestKickoffTrackerPrunesStale(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	tr := scheduling.NewKickoffTracker(clk, 3*time.Hour, 6*time.Hour)
	ctx := context.Background()
	tr.ObserveKickoff(ctx, schedComp, "old", clk.now.Add(-10*time.Hour)) // long finished
	prox, _ := tr.Proximity(ctx, schedComp)
	if prox.AnyLive || prox.HasUpcoming {
		t.Errorf("stale fixture must be pruned: %+v", prox)
	}
}

// fakeSchedule lets the advisor test drive proximity deterministically.
type fakeSchedule struct{ p scheduling.MatchProximity }

func (f fakeSchedule) Proximity(_ context.Context, _ uuid.UUID) (scheduling.MatchProximity, error) {
	return f.p, nil
}

func newAdvisor(t *testing.T, sched scheduling.MatchScheduleSource, b scheduling.BudgetController, mode oddsmode.Mode) *scheduling.OddsAdvisor {
	t.Helper()
	dyn, err := syncdom.NewDynamicPollPolicy(
		"the_odds_api", syncdom.TypeOdds,
		[]syncdom.PollWindow{
			{MaxLeadTime: 6 * time.Hour, Interval: 15 * time.Minute},
			{MaxLeadTime: 48 * time.Hour, Interval: time.Hour},
			{MaxLeadTime: 7 * 24 * time.Hour, Interval: 6 * time.Hour},
		},
		time.Minute, 12*time.Hour, true,
	)
	if err != nil {
		t.Fatal(err)
	}
	budgets := map[string]scheduling.BudgetController{}
	if b != nil {
		budgets["the_odds_api"] = b
	}
	clk := &stepClock{now: time.Now()}
	modeCtl := oddsmode.NewController(oddsmode.StaticSource{M: mode}, oddsmode.DefaultProfiles(), oddsmode.ModeNormal, time.Second, clk)
	return scheduling.NewOddsAdvisor(scheduling.Config{
		DynamicPolicies: []syncdom.DynamicPollPolicy{dyn},
		Schedule:        sched,
		Budgets:         budgets,
		Mode:            modeCtl,
		Logger:          zerolog.Nop(),
	})
}

func oddsLane() scheduler.Lane {
	return scheduler.Lane{ProviderID: "the_odds_api", SyncType: syncdom.TypeOdds, CompetitionID: schedComp}
}

func TestAdvisorLeavesNonOddsLanesUntouched(t *testing.T) {
	adv := newAdvisor(t, fakeSchedule{}, nil, oddsmode.ModeNormal)
	lane := scheduler.Lane{ProviderID: "api_football", SyncType: syncdom.TypeFixtures, CompetitionID: schedComp}
	a := adv.Advise(context.Background(), lane, 30*time.Minute, time.Now())
	if a.Skip || a.Interval != 0 {
		t.Errorf("non-odds lane must pass through untouched: %+v", a)
	}
}

func TestAdvisorLiveTightensInterval(t *testing.T) {
	adv := newAdvisor(t, fakeSchedule{p: scheduling.MatchProximity{AnyLive: true}}, nil, oddsmode.ModeNormal)
	a := adv.Advise(context.Background(), oddsLane(), 5*time.Minute, time.Now())
	if a.Skip || a.Interval != time.Minute {
		t.Errorf("live lane should poll every minute: %+v", a)
	}
}

func TestAdvisorWorldCupMultipliesFrequency(t *testing.T) {
	sched := fakeSchedule{p: scheduling.MatchProximity{HasUpcoming: true, NearestKickoff: 3 * time.Hour}}
	normal := newAdvisor(t, sched, nil, oddsmode.ModeNormal)
	worldcup := newAdvisor(t, sched, nil, oddsmode.ModeWorldCup)
	an := normal.Advise(context.Background(), oddsLane(), 5*time.Minute, time.Now())
	aw := worldcup.Advise(context.Background(), oddsLane(), 5*time.Minute, time.Now())
	if aw.Interval >= an.Interval {
		t.Errorf("worldcup must poll more often: normal=%v worldcup=%v", an.Interval, aw.Interval)
	}
}

func TestAdvisorBudgetSkipsDistantUnderPressure(t *testing.T) {
	clk := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	mgr := budget.NewManager("the_odds_api", budget.Caps{Monthly: 10}, budget.NewMemoryStore(clk.Now), clk)
	recordN(t, mgr, 6) // 0.6 pressure → drop Future

	// A distant fixture (>72h) under pressure must be skipped...
	distant := newAdvisor(t, fakeSchedule{p: scheduling.MatchProximity{HasUpcoming: true, NearestKickoff: 5 * 24 * time.Hour}}, mgr, oddsmode.ModeNormal)
	a := distant.Advise(context.Background(), oddsLane(), 5*time.Minute, time.Now())
	if !a.Skip {
		t.Errorf("distant fixture under budget pressure must skip: %+v", a)
	}

	// ...while a live match is never starved.
	live := newAdvisor(t, fakeSchedule{p: scheduling.MatchProximity{AnyLive: true}}, mgr, oddsmode.ModeNormal)
	al := live.Advise(context.Background(), oddsLane(), 5*time.Minute, time.Now())
	if al.Skip {
		t.Errorf("live match must never be skipped for budget: %+v", al)
	}
}
