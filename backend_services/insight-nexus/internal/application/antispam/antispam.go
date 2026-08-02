// Anti-Spam Engine — Sprint 4 Part 11.
//
// Deterministic publication budgets over the PERSISTED publication
// log (nexus.publication_log): per-agent / per-cluster / per-trend /
// per-match cooldowns plus hourly + daily limits. Every suppression
// returns a machine-readable explanation — "explain every
// suppression" is a platform non-negotiable.
package antispam

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// Policy — configurable budgets (config-driven; persisted publication
// history makes them enforceable across restarts).
type Policy struct {
	AgentCooldown   time.Duration // min gap between ANY two posts by one agent
	ClusterCooldown time.Duration // min gap between posts on one story
	TrendCooldown   time.Duration // min gap between posts on one trend id
	MatchCooldown   time.Duration // min gap between one agent's posts on one match
	HourlyLimit     int           // per agent
	DailyLimit      int           // per agent
}

// DefaultPolicy — conservative defaults; override via config.
func DefaultPolicy() Policy {
	return Policy{
		AgentCooldown:   5 * time.Minute,
		ClusterCooldown: 15 * time.Minute,
		TrendCooldown:   30 * time.Minute,
		MatchCooldown:   10 * time.Minute,
		HourlyLimit:     6,
		DailyLimit:      30,
	}
}

// Log is the persistence port (implemented by postgres + inmemory).
type Log interface {
	// Record one successful publication (called AFTER the Social post
	// lands).
	Record(ctx context.Context, e Entry) error
	// LastByAgent/Cluster/Trend/AgentMatch return the newest
	// publication time for the scope, or zero time when none.
	LastByAgent(ctx context.Context, agentID uuid.UUID) (time.Time, error)
	LastByCluster(ctx context.Context, clusterID uuid.UUID) (time.Time, error)
	LastByTrend(ctx context.Context, trendID string) (time.Time, error)
	LastByAgentMatch(ctx context.Context, agentID uuid.UUID, matchID string) (time.Time, error)
	// CountByAgentSince — publications by the agent since `since`.
	CountByAgentSince(ctx context.Context, agentID uuid.UUID, since time.Time) (int, error)
}

// Entry — one persisted publication event.
type Entry struct {
	AgentID     uuid.UUID
	ClusterID   uuid.UUID
	TrendID     string
	MatchID     string
	PublishedAt time.Time
}

// Verdict — allowed or an explained suppression.
type Verdict struct {
	Allowed bool
	Reason  string // machine-readable, empty when allowed
}

func suppressed(format string, args ...any) Verdict {
	return Verdict{Allowed: false, Reason: fmt.Sprintf(format, args...)}
}

// Metrics — observability seam (nexus_spam_prevented_total).
type Metrics interface {
	SpamPrevented(rule string)
}

type Engine struct {
	policy  Policy
	log     Log
	metrics Metrics
	now     func() time.Time
}

func New(policy Policy, log Log, metrics Metrics, now func() time.Time) *Engine {
	if now == nil {
		now = func() time.Time { return time.Now().UTC() }
	}
	return &Engine{policy: policy, log: log, metrics: metrics, now: now}
}

// Check evaluates every budget; the FIRST violated rule explains the
// suppression (rules ordered cheapest-to-strictest for stable
// explanations).
func (e *Engine) Check(
	ctx context.Context,
	agentID uuid.UUID,
	clusterID uuid.UUID,
	trendID string,
	matchID string,
) (Verdict, error) {
	now := e.now()

	if last, err := e.log.LastByAgent(ctx, agentID); err != nil {
		return Verdict{}, err
	} else if gap := now.Sub(last); !last.IsZero() && gap < e.policy.AgentCooldown {
		return e.prevent("agent_cooldown",
			"agent_cooldown: last post %s ago, cooldown %s", gap.Round(time.Second), e.policy.AgentCooldown), nil
	}
	if clusterID != uuid.Nil {
		if last, err := e.log.LastByCluster(ctx, clusterID); err != nil {
			return Verdict{}, err
		} else if gap := now.Sub(last); !last.IsZero() && gap < e.policy.ClusterCooldown {
			return e.prevent("cluster_cooldown",
				"cluster_cooldown: story posted %s ago, cooldown %s", gap.Round(time.Second), e.policy.ClusterCooldown), nil
		}
	}
	if trendID != "" {
		if last, err := e.log.LastByTrend(ctx, trendID); err != nil {
			return Verdict{}, err
		} else if gap := now.Sub(last); !last.IsZero() && gap < e.policy.TrendCooldown {
			return e.prevent("trend_cooldown",
				"trend_cooldown: trend posted %s ago, cooldown %s", gap.Round(time.Second), e.policy.TrendCooldown), nil
		}
	}
	if matchID != "" {
		if last, err := e.log.LastByAgentMatch(ctx, agentID, matchID); err != nil {
			return Verdict{}, err
		} else if gap := now.Sub(last); !last.IsZero() && gap < e.policy.MatchCooldown {
			return e.prevent("match_cooldown",
				"match_cooldown: agent posted on match %s ago, cooldown %s", gap.Round(time.Second), e.policy.MatchCooldown), nil
		}
	}
	if e.policy.HourlyLimit > 0 {
		n, err := e.log.CountByAgentSince(ctx, agentID, now.Add(-time.Hour))
		if err != nil {
			return Verdict{}, err
		}
		if n >= e.policy.HourlyLimit {
			return e.prevent("hourly_limit",
				"hourly_limit: %d/%d posts in the last hour", n, e.policy.HourlyLimit), nil
		}
	}
	if e.policy.DailyLimit > 0 {
		n, err := e.log.CountByAgentSince(ctx, agentID, now.Add(-24*time.Hour))
		if err != nil {
			return Verdict{}, err
		}
		if n >= e.policy.DailyLimit {
			return e.prevent("daily_limit",
				"daily_limit: %d/%d posts in the last 24h", n, e.policy.DailyLimit), nil
		}
	}
	return Verdict{Allowed: true}, nil
}

func (e *Engine) prevent(rule, format string, args ...any) Verdict {
	if e.metrics != nil {
		e.metrics.SpamPrevented(rule)
	}
	return suppressed(format, args...)
}

// RecordPublication persists the publication event the budgets read.
func (e *Engine) RecordPublication(
	ctx context.Context,
	agentID, clusterID uuid.UUID,
	trendID, matchID string,
) error {
	return e.log.Record(ctx, Entry{
		AgentID:     agentID,
		ClusterID:   clusterID,
		TrendID:     trendID,
		MatchID:     matchID,
		PublishedAt: e.now(),
	})
}
