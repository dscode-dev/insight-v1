package scheduling

import (
	"context"
	"time"

	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-sports-hub/internal/application/budget"
	"github.com/konoha-labs/insight-sports-hub/internal/application/oddsmode"
	"github.com/konoha-labs/insight-sports-hub/internal/application/scheduler"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

// BudgetController is the slice of budget.Manager the advisor needs.
type BudgetController interface {
	Allow(ctx context.Context, priority budget.Priority) (budget.Decision, error)
}

// ModeController is the slice of oddsmode.Controller the advisor needs.
type ModeController interface {
	Current(ctx context.Context) (oddsmode.Mode, oddsmode.Profile)
}

// OddsAdvisor implements scheduler.SchedulingAdvisor. It combines, in
// order: kickoff-proximity dynamic windows, operational-mode poll
// multiplier, and budget-pressure interval scaling / hard skips.
//
// Only lanes that have a registered DynamicPollPolicy are adjusted;
// every other lane passes through untouched (Advise returns the zero
// Advice, so the Planner keeps the static interval).
type OddsAdvisor struct {
	dynamic    map[string]syncdom.DynamicPollPolicy // key: provider|sync_type
	schedule   MatchScheduleSource
	budgets    map[string]BudgetController // key: provider
	mode       ModeController
	liveWindow time.Duration
	logger     zerolog.Logger
}

// Config bundles the advisor's collaborators.
type Config struct {
	// DynamicPolicies keyed by provider id; each provides its lanes.
	DynamicPolicies []syncdom.DynamicPollPolicy
	Schedule        MatchScheduleSource
	// Budgets keyed by provider id. Optional — a lane whose provider
	// has no budget controller skips budget gating.
	Budgets map[string]BudgetController
	Mode    ModeController
	Logger  zerolog.Logger
}

func NewOddsAdvisor(cfg Config) *OddsAdvisor {
	dyn := make(map[string]syncdom.DynamicPollPolicy, len(cfg.DynamicPolicies))
	for _, p := range cfg.DynamicPolicies {
		dyn[laneKey(p.ProviderID, p.SyncType)] = p
	}
	return &OddsAdvisor{
		dynamic:  dyn,
		schedule: cfg.Schedule,
		budgets:  cfg.Budgets,
		mode:     cfg.Mode,
		logger:   cfg.Logger,
	}
}

func laneKey(provider string, st syncdom.SyncType) string {
	return provider + "|" + string(st)
}

// Advise resolves the effective interval + skip decision for a lane.
func (a *OddsAdvisor) Advise(
	ctx context.Context, lane scheduler.Lane, base time.Duration, now time.Time,
) scheduler.Advice {
	dyn, ok := a.dynamic[laneKey(lane.ProviderID, lane.SyncType)]
	if !ok {
		return scheduler.Advice{} // not an odds-managed lane — leave base.
	}

	// 1. Kickoff proximity.
	ttk, live := a.proximity(ctx, lane)

	// 2. Dynamic window → interval.
	interval, enabled := dyn.EffectiveInterval(ttk, live, false)
	if !enabled {
		// Finished/disabled — back off to the default cadence so the
		// lane is rechecked occasionally (new fixtures get discovered).
		interval = dyn.DefaultInterval
		return scheduler.Advice{Interval: interval, Skip: true, Reason: "no_active_fixtures"}
	}

	// 3. Operational mode multiplier.
	if a.mode != nil {
		_, profile := a.mode.Current(ctx)
		if profile.PollMultiplier > 0 {
			interval = scaleDuration(interval, profile.PollMultiplier)
		}
	}

	// 4. Budget pressure → interval scaling + hard skip.
	reason := ""
	skip := false
	if bc, ok := a.budgets[lane.ProviderID]; ok && bc != nil {
		decision, err := bc.Allow(ctx, priorityFor(ttk, live))
		if err != nil {
			a.logger.Warn().Err(err).Str("provider", lane.ProviderID).
				Msg("odds_advisor_budget_error_fail_open")
		} else {
			if decision.IntervalScale > 0 {
				interval = scaleDuration(interval, decision.IntervalScale)
			}
			if !decision.Allowed {
				skip = true
				reason = decision.Reason
			}
		}
	}

	return scheduler.Advice{Interval: interval, Skip: skip, Reason: reason}
}

func (a *OddsAdvisor) proximity(ctx context.Context, lane scheduler.Lane) (time.Duration, bool) {
	if a.schedule == nil {
		// No schedule data — treat as distant future (DefaultInterval).
		return time.Duration(1<<62 - 1), false
	}
	prox, err := a.schedule.Proximity(ctx, lane.CompetitionID)
	if err != nil {
		a.logger.Warn().Err(err).Str("competition", lane.CompetitionID.String()).
			Msg("odds_advisor_schedule_error_fail_open")
		return time.Duration(1<<62 - 1), false
	}
	if prox.AnyLive {
		return 0, true
	}
	if prox.HasUpcoming {
		return prox.NearestKickoff, false
	}
	// Nothing upcoming, nothing live → distant tier.
	return time.Duration(1<<62 - 1), false
}

// priorityFor maps proximity to a budget priority.
func priorityFor(ttk time.Duration, live bool) budget.Priority {
	switch {
	case live:
		return budget.PriorityLive
	case ttk < 24*time.Hour:
		return budget.PriorityWithin24h
	case ttk < 72*time.Hour:
		return budget.PriorityWithin72h
	default:
		return budget.PriorityFuture
	}
}

func scaleDuration(d time.Duration, factor float64) time.Duration {
	if factor <= 0 {
		return d
	}
	return time.Duration(float64(d) * factor)
}

var _ scheduler.SchedulingAdvisor = (*OddsAdvisor)(nil)
