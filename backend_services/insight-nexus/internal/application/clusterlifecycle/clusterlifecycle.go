// Package clusterlifecycle — the Cluster Lifecycle Engine (Sprint 3.5).
//
// Narratives are FINITE. A cluster closes when:
//
//	COMPLETED — a RETROSPECTIVE draft was generated, a confirmed
//	            (terminal) lifecycle trend arrived, or the match ended.
//	FAILED    — the trend lifecycle FAILED while the cluster's
//	            confidence had collapsed below the floor.
//	EXPIRED   — no activity for longer than the configured threshold
//	            (default 90 minutes; enforced on-touch by the
//	            clustering engine using the same rule).
//
// Closed clusters are never reused: the repository's GetActive skips
// them, so the next trend opens a fresh cluster (reopen behaviour).
// Every closure carries a stable close_reason — auditable end to end.
package clusterlifecycle

import (
	"context"
	"fmt"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

var clusterClosuresTotal = promauto.NewCounterVec(prometheus.CounterOpts{
	Name: "nexus_cluster_closures_total",
	Help: "Story clusters closed, by terminal state and reason.",
}, []string{"state", "reason"})

// Config — every threshold configurable.
type Config struct {
	// ExpireAfter — inactivity window before a cluster expires.
	ExpireAfter time.Duration
	// FailureConfidenceFloor — a FAILED trend closes the cluster only
	// when its confidence has collapsed below this floor (a strong
	// story survives one failed member).
	FailureConfidenceFloor float64
}

func (c Config) defaults() Config {
	if c.ExpireAfter <= 0 {
		c.ExpireAfter = 90 * time.Minute
	}
	if c.FailureConfidenceFloor <= 0 {
		c.FailureConfidenceFloor = 0.5
	}
	return c
}

type Engine struct {
	clusters ports.ClusterRepository
	cfg      Config
	logger   zerolog.Logger
	now      func() time.Time
}

func New(
	clusters ports.ClusterRepository, cfg Config, logger zerolog.Logger,
	now func() time.Time,
) *Engine {
	if now == nil {
		now = time.Now
	}
	return &Engine{clusters: clusters, cfg: cfg.defaults(), logger: logger, now: now}
}

// Config exposes the effective configuration (the clustering engine
// shares the expiry threshold so on-touch expiry uses the same rule).
func (e *Engine) ExpireAfter() time.Duration { return e.cfg.ExpireAfter }

// EvaluateTrend applies the trend-driven close rules to an open
// cluster after it absorbed the trend. Returns the (possibly closed)
// cluster and whether it closed.
func (e *Engine) EvaluateTrend(
	ctx context.Context, c cluster.TrendCluster, ev trend.Event,
) (cluster.TrendCluster, bool, error) {
	if !c.IsOpen() {
		return c, false, nil
	}
	switch ev.LifecycleState {
	case "confirmed":
		// Terminal lifecycle trend → the story completed.
		return e.close(ctx, c, cluster.ClusterCompleted, cluster.ReasonLifecycleConfirmed)
	case "failed":
		if c.Confidence < e.cfg.FailureConfidenceFloor {
			return e.close(ctx, c, cluster.ClusterFailed, cluster.ReasonLifecycleFailed)
		}
	}
	return c, false, nil
}

// CompleteOnRetrospective closes the cluster after a RETROSPECTIVE
// draft was generated for it.
func (e *Engine) CompleteOnRetrospective(
	ctx context.Context, c cluster.TrendCluster,
) (cluster.TrendCluster, bool, error) {
	return e.close(ctx, c, cluster.ClusterCompleted, cluster.ReasonRetrospectiveDraft)
}

// CloseForMatchEnd closes every open cluster on the match (the match
// end sweep calls this). Returns how many clusters closed.
func (e *Engine) CloseForMatchEnd(ctx context.Context, matchID string) (int, error) {
	open, err := e.clusters.ListActiveByMatch(ctx, matchID)
	if err != nil {
		return 0, fmt.Errorf("clusterlifecycle: list active: %w", err)
	}
	closed := 0
	for _, c := range open {
		if _, didClose, err := e.close(
			ctx, c, cluster.ClusterCompleted, cluster.ReasonMatchFinished,
		); err != nil {
			return closed, err
		} else if didClose {
			closed++
		}
	}
	return closed, nil
}

func (e *Engine) close(
	ctx context.Context, c cluster.TrendCluster, st cluster.State, reason string,
) (cluster.TrendCluster, bool, error) {
	if !c.Close(st, reason, e.now()) {
		return c, false, nil
	}
	if err := e.clusters.Save(ctx, c); err != nil {
		return c, false, fmt.Errorf("clusterlifecycle: save: %w", err)
	}
	clusterClosuresTotal.WithLabelValues(string(st), reason).Inc()
	e.logger.Info().
		Str("cluster_id", c.ID.String()).
		Str("match_id", c.MatchID).
		Str("cluster_type", string(c.ClusterType)).
		Str("state", string(st)).
		Str("reason", reason).
		Msg("cluster_closed")
	return c, true, nil
}
