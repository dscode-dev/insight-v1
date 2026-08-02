// Package narrativehealth — the Narrative Health Engine (Sprint 3.5).
//
// Measures story QUALITY per cluster: a deterministic 0..1 health
// score over confidence, trend diversity, confirmation rate, failure
// state and story continuity. Used for metrics, dashboards and admin
// visibility ONLY — publication decisions never read it (yet).
package narrativehealth

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/evolution"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

var storyHealthScore = promauto.NewHistogram(prometheus.HistogramOpts{
	Name:    "nexus_story_health_score",
	Help:    "Distribution of computed story health scores.",
	Buckets: prometheus.LinearBuckets(0, 0.1, 11),
})

// StoryHealth — the computed quality view of one cluster.
type StoryHealth struct {
	ClusterID     uuid.UUID     `json:"cluster_id"`
	MatchID       string        `json:"match_id"`
	ClusterType   string        `json:"cluster_type"`
	TrendCount    int           `json:"trend_count"`
	DraftCount    int           `json:"draft_count"`
	AvgConfidence float64       `json:"avg_confidence"`
	Lifespan      time.Duration `json:"lifespan"`
	State         string        `json:"state"`
	HealthScore   float64       `json:"health_score"`
}

// Weights — every factor configurable; defaults documented inline.
type Weights struct {
	Confidence   float64 // strongest member confidence
	Diversity    float64 // distinct trend types (corroboration)
	Confirmation float64 // CONFIRMATION drafts / drafts
	Continuity   float64 // the story actually developed (follow-ups)
	FailurePen   float64 // subtracted when the cluster FAILED
	ExpiryPen    float64 // subtracted when the cluster EXPIRED
}

func (w Weights) defaults() Weights {
	if w.Confidence == 0 {
		w.Confidence = 0.40
	}
	if w.Diversity == 0 {
		w.Diversity = 0.20
	}
	if w.Confirmation == 0 {
		w.Confirmation = 0.20
	}
	if w.Continuity == 0 {
		w.Continuity = 0.20
	}
	if w.FailurePen == 0 {
		w.FailurePen = 0.25
	}
	if w.ExpiryPen == 0 {
		w.ExpiryPen = 0.10
	}
	return w
}

type Engine struct {
	clusters  ports.ClusterRepository
	evolution ports.EvolutionRepository
	weights   Weights
	now       func() time.Time
}

func New(
	clusters ports.ClusterRepository,
	evolutionRepo ports.EvolutionRepository,
	weights Weights,
	now func() time.Time,
) *Engine {
	if now == nil {
		now = time.Now
	}
	return &Engine{
		clusters: clusters, evolution: evolutionRepo,
		weights: weights.defaults(), now: now,
	}
}

// Compute resolves the health of one cluster. Deterministic over the
// cluster row + its evolution records.
func (e *Engine) Compute(ctx context.Context, c cluster.TrendCluster) (StoryHealth, error) {
	records, err := e.evolution.ListByCluster(ctx, c.ID, 200)
	if err != nil {
		return StoryHealth{}, fmt.Errorf("narrativehealth: evolution: %w", err)
	}

	confirmations, followUps := 0, 0
	for _, rec := range records {
		switch rec.DraftType {
		case evolution.Confirmation:
			confirmations++
		case evolution.FollowUp:
			followUps++
		}
	}

	w := e.weights
	score := w.Confidence * clamp(c.Confidence)
	// Diversity: 3+ distinct member types = a fully corroborated story.
	score += w.Diversity * clamp(float64(len(c.TrendTypes))/3.0)
	if len(records) > 0 {
		score += w.Confirmation * clamp(float64(confirmations)/float64(len(records)))
	}
	// Continuity: the story produced follow-ups (it developed) rather
	// than a single isolated communication.
	if followUps > 0 || confirmations > 0 {
		score += w.Continuity
	}
	switch c.State {
	case cluster.ClusterFailed:
		score -= w.FailurePen
	case cluster.ClusterExpired:
		score -= w.ExpiryPen
	}
	score = clamp(score)
	storyHealthScore.Observe(score)

	end := e.now().UTC()
	if c.ClosedAt != nil {
		end = *c.ClosedAt
	}
	opened := c.OpenedAt
	if opened.IsZero() {
		opened = c.CreatedAt
	}
	return StoryHealth{
		ClusterID:     c.ID,
		MatchID:       c.MatchID,
		ClusterType:   string(c.ClusterType),
		TrendCount:    len(c.TrendIDs),
		DraftCount:    len(records),
		AvgConfidence: c.Confidence,
		Lifespan:      end.Sub(opened),
		State:         string(stateOrActive(c)),
		HealthScore:   round4(score),
	}, nil
}

// ComputeRecent — health for the newest `limit` clusters (the admin
// endpoint + dashboards).
func (e *Engine) ComputeRecent(ctx context.Context, limit int) ([]StoryHealth, error) {
	clusters, err := e.clusters.List(ctx, limit)
	if err != nil {
		return nil, fmt.Errorf("narrativehealth: clusters: %w", err)
	}
	out := make([]StoryHealth, 0, len(clusters))
	for _, c := range clusters {
		h, err := e.Compute(ctx, c)
		if err != nil {
			return nil, err
		}
		out = append(out, h)
	}
	return out, nil
}

func stateOrActive(c cluster.TrendCluster) cluster.State {
	if c.State == "" {
		return cluster.ClusterActive
	}
	return c.State
}

func clamp(v float64) float64 {
	if v < 0 {
		return 0
	}
	if v > 1 {
		return 1
	}
	return v
}

func round4(v float64) float64 {
	return float64(int(v*10000+0.5)) / 10000
}
