// Package matchsweep — the Match End Sweep (Sprint 3.5).
//
// When a terminal match marker arrives (a game_state_change into a
// finished state, a fulltime impact event, or an explicit
// match_finished trend), every lingering narrative on the match is
// closed: agent states in OBSERVING/TRACKING/ALERTING transition to
// RETROSPECTIVE, and every open cluster completes with reason
// match_finished. No active states remain after match completion.
//
// Deterministic, isolated: the sweep depends on domain types + ports
// only — never on sibling application packages.
package matchsweep

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/domain/state"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

var (
	matchSweepsTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "nexus_match_sweeps_total",
		Help: "Match end sweeps executed.",
	})
	sweepRetrospectivesTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "nexus_sweep_retrospectives_total",
		Help: "Agent states moved to RETROSPECTIVE by the match end sweep.",
	})
)

// ClusterCloser is the slice of the cluster lifecycle engine the sweep
// needs (interface so the engines stay decoupled).
type ClusterCloser interface {
	CloseForMatchEnd(ctx context.Context, matchID string) (int, error)
}

// Config — which markers mean "the match is over". Configurable so
// future Atlas taxonomy growth is a config change.
type Config struct {
	// TerminalGameStates — game_state_change destinations that end the
	// match.
	TerminalGameStates []string
	// TerminalImpactCategories — impact categories that end the match.
	TerminalImpactCategories []string
}

func (c Config) defaults() Config {
	if len(c.TerminalGameStates) == 0 {
		c.TerminalGameStates = []string{"fulltime", "finished", "post_match"}
	}
	if len(c.TerminalImpactCategories) == 0 {
		c.TerminalImpactCategories = []string{"fulltime", "result"}
	}
	return c
}

type Engine struct {
	states   ports.AgentStateRepository
	clusters ClusterCloser
	cfg      Config
	logger   zerolog.Logger
	now      func() time.Time
}

func New(
	states ports.AgentStateRepository,
	clusters ClusterCloser,
	cfg Config,
	logger zerolog.Logger,
	now func() time.Time,
) *Engine {
	if now == nil {
		now = time.Now
	}
	return &Engine{
		states: states, clusters: clusters, cfg: cfg.defaults(),
		logger: logger, now: now,
	}
}

// Result — what one sweep did.
type Result struct {
	Swept          bool
	Retrospectives int
	ClustersClosed int
}

// MaybeSweep inspects the trend for a terminal match marker and runs
// the sweep when one is present.
func (e *Engine) MaybeSweep(ctx context.Context, ev trend.Event) (Result, error) {
	if !e.isMatchEnd(ev) {
		return Result{}, nil
	}
	return e.Sweep(ctx, ev.MatchID)
}

// Sweep closes every lingering narrative on the match.
func (e *Engine) Sweep(ctx context.Context, matchID string) (Result, error) {
	now := e.now().UTC()
	matchSweepsTotal.Inc()

	active, err := e.states.ListActiveByMatch(ctx, matchID)
	if err != nil {
		return Result{}, fmt.Errorf("matchsweep: list states: %w", err)
	}
	retros := 0
	for _, s := range active {
		if s.Apply(state.Retrospective, "match_finished_sweep", now) {
			if err := e.states.Save(ctx, s); err != nil {
				return Result{}, fmt.Errorf("matchsweep: save state: %w", err)
			}
			retros++
			sweepRetrospectivesTotal.Inc()
		}
	}

	closed, err := e.clusters.CloseForMatchEnd(ctx, matchID)
	if err != nil {
		return Result{}, fmt.Errorf("matchsweep: close clusters: %w", err)
	}

	e.logger.Info().
		Str("match_id", matchID).
		Int("retrospectives", retros).
		Int("clusters_closed", closed).
		Msg("match_end_sweep_completed")
	return Result{Swept: true, Retrospectives: retros, ClustersClosed: closed}, nil
}

// isMatchEnd — deterministic terminal-marker detection over the
// trend's own fields (never re-deriving Atlas intelligence).
func (e *Engine) isMatchEnd(ev trend.Event) bool {
	switch ev.TrendType {
	case "match_finished":
		return true
	case "game_state_change":
		to, _ := ev.Metrics["to"].(string)
		return contains(e.cfg.TerminalGameStates, to)
	case "impact_assessment":
		category, _ := ev.Metrics["category"].(string)
		return contains(e.cfg.TerminalImpactCategories, category)
	}
	return false
}

func contains(haystack []string, needle string) bool {
	for _, h := range haystack {
		if strings.EqualFold(h, needle) {
			return true
		}
	}
	return false
}
