// Package clustering — the Trend Clustering engine.
//
// Folds each consumed trend into its match's ACTIVE story cluster
// (one per (match, cluster type)). Communication downstream operates
// on clusters, not raw trends: pressure_building + dominance_pattern +
// momentum_shift become ONE attacking-pressure story, not three
// parallel communications.
package clustering

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

var trendClustersCreatedTotal = promauto.NewCounterVec(prometheus.CounterOpts{
	Name: "trend_clusters_created_total",
	Help: "New story clusters opened, by cluster type.",
}, []string{"cluster_type"})

var trendClustersExpiredTotal = promauto.NewCounterVec(prometheus.CounterOpts{
	Name: "trend_clusters_expired_on_touch_total",
	Help: "Stale clusters expired when a new trend touched their story.",
}, []string{"cluster_type"})

type Engine struct {
	clusters ports.ClusterRepository
	now      func() time.Time
	// expireAfter — inactivity window (Sprint 3.5). A stale open
	// cluster is closed as EXPIRED on touch and a FRESH cluster opens
	// for the new trend (closed clusters are never reused).
	expireAfter time.Duration
}

func New(clusters ports.ClusterRepository, now func() time.Time, expireAfter time.Duration) *Engine {
	if now == nil {
		now = time.Now
	}
	if expireAfter <= 0 {
		expireAfter = 90 * time.Minute
	}
	return &Engine{clusters: clusters, now: now, expireAfter: expireAfter}
}

// Assign folds one trend into its story cluster, creating the cluster
// when this is the story's first trend. Returns the updated cluster
// and whether it was newly created.
func (e *Engine) Assign(ctx context.Context, ev trend.Event) (cluster.TrendCluster, bool, error) {
	clusterType, err := cluster.TypeFor(ev.TrendType, ev.Category)
	if err != nil {
		return cluster.TrendCluster{}, false, fmt.Errorf("clustering: %w", err)
	}
	now := e.now().UTC()

	existing, err := e.clusters.GetActive(ctx, ev.MatchID, clusterType)
	created := false
	switch {
	case err == nil:
		// On-touch expiry: a stale story closes and a fresh one opens
		// for the new trend (Sprint 3.5 — narratives are finite).
		if existing.StaleAfter(e.expireAfter, now) {
			if existing.Close(cluster.ClusterExpired, cluster.ReasonInactivity, now) {
				if serr := e.clusters.Save(ctx, existing); serr != nil {
					return cluster.TrendCluster{}, false, fmt.Errorf("clustering: expire: %w", serr)
				}
				trendClustersExpiredTotal.WithLabelValues(string(clusterType)).Inc()
			}
			existing = newCluster(ev.MatchID, clusterType, now)
			created = true
			trendClustersCreatedTotal.WithLabelValues(string(clusterType)).Inc()
		}
	case errors.Is(err, ports.ErrNotFound):
		existing = newCluster(ev.MatchID, clusterType, now)
		created = true
		trendClustersCreatedTotal.WithLabelValues(string(clusterType)).Inc()
	default:
		return cluster.TrendCluster{}, false, fmt.Errorf("clustering: get active: %w", err)
	}

	existing.Absorb(ev.TrendID, ev.TrendType, ev.Confidence, now)
	if err := e.clusters.Save(ctx, existing); err != nil {
		return cluster.TrendCluster{}, false, fmt.Errorf("clustering: save: %w", err)
	}
	return existing, created, nil
}

func newCluster(matchID string, clusterType cluster.Type, now time.Time) cluster.TrendCluster {
	return cluster.TrendCluster{
		ID:          uuid.New(),
		MatchID:     matchID,
		ClusterType: clusterType,
		State:       cluster.ClusterActive,
		OpenedAt:    now,
		CreatedAt:   now,
		UpdatedAt:   now,
	}
}
