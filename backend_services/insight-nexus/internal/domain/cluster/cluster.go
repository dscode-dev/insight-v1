// Package cluster — trend clustering domain.
//
// Multiple Atlas trends often describe ONE story (pressure building +
// dominance + momentum = "attacking pressure"). Communication operates
// on clusters, not raw trends, so one story produces one evolving
// narrative instead of three parallel drafts.
//
// The trend-type → cluster-type mapping is deterministic and total
// over Atlas's taxonomy. Unknown future types fall back to a cluster
// derived from their category, so taxonomy growth never drops trends.
package cluster

import (
	"errors"
	"time"

	"github.com/google/uuid"
)

// Type — the five V1 cluster types.
type Type string

const (
	AttackingPressure Type = "ATTACKING_PRESSURE"
	MarketConfidence  Type = "MARKET_CONFIDENCE"
	RiskEscalation    Type = "RISK_ESCALATION"
	NarrativeShift    Type = "NARRATIVE_SHIFT"
	HistoricalRepeat  Type = "HISTORICAL_REPEAT"
)

// typeOf maps every Atlas trend type to its story cluster.
var typeOf = map[string]Type{
	// Match dynamics → one attacking-pressure story.
	"pressure_building":     AttackingPressure,
	"dominance_pattern":     AttackingPressure,
	"momentum_shift":        AttackingPressure,
	"tempo_change":          AttackingPressure,
	"imminent_breakthrough": AttackingPressure,
	// Market behaviour → one market-confidence story.
	"market_shift":        MarketConfidence,
	"market_acceleration": MarketConfidence,
	"market_disagreement": MarketConfidence,
	"market_anomaly":      MarketConfidence,
	"market_conviction":   MarketConfidence,
	// Risk → one risk story.
	"risk_increase":     RiskEscalation,
	"risk_escalation":   RiskEscalation,
	"game_state_change": RiskEscalation,
	"impact_assessment": RiskEscalation,
	// Narrative → one narrative story.
	"narrative_conflict":   NarrativeShift,
	"narrative_divergence": NarrativeShift,
	"sentiment_shift":      NarrativeShift,
	"community_signal":     NarrativeShift,
	// Historical → one history story.
	"historical_deviation":  HistoricalRepeat,
	"historical_pattern":    HistoricalRepeat,
	"historical_similarity": HistoricalRepeat,
}

// categoryFallback covers future trend types by their Atlas category.
var categoryFallback = map[string]Type{
	"ninja":    MarketConfidence,
	"pulse":    AttackingPressure,
	"oracle":   HistoricalRepeat,
	"sentinel": RiskEscalation,
	"echo":     NarrativeShift,
	"fusion":   RiskEscalation,
}

// ErrUnclusterable — neither the type nor the category maps.
var ErrUnclusterable = errors.New("cluster: trend not clusterable")

// TypeFor resolves the cluster type for a trend. Deterministic + total
// over the current taxonomy; future types resolve via category.
func TypeFor(trendType, category string) (Type, error) {
	if t, ok := typeOf[trendType]; ok {
		return t, nil
	}
	if t, ok := categoryFallback[category]; ok {
		return t, nil
	}
	return "", ErrUnclusterable
}

// State — the narrative lifecycle of a cluster (Sprint 3.5).
// Narratives are FINITE: every cluster eventually completes, fails or
// expires; closed clusters are never reused — a new trend for the same
// story opens a fresh cluster.
type State string

const (
	ClusterActive    State = "ACTIVE"
	ClusterCompleted State = "COMPLETED"
	ClusterFailed    State = "FAILED"
	ClusterExpired   State = "EXPIRED"
)

// Close reasons — stable audit slugs.
const (
	ReasonRetrospectiveDraft = "retrospective_draft"
	ReasonLifecycleConfirmed = "lifecycle_confirmed"
	ReasonLifecycleFailed    = "lifecycle_failed_confidence_collapse"
	ReasonMatchFinished      = "match_finished"
	ReasonInactivity         = "inactivity_expired"
)

// TrendCluster is one story for one match.
type TrendCluster struct {
	ID          uuid.UUID
	MatchID     string
	ClusterType Type
	// TrendIDs — every member trend, in arrival order.
	TrendIDs []string
	// TrendTypes — the distinct member types (story composition).
	TrendTypes []string
	// Confidence — the strongest member confidence seen so far.
	Confidence float64
	// State — narrative lifecycle. Only ACTIVE clusters absorb trends.
	State State
	// OpenedAt — when the story opened (CreatedAt alias, persisted
	// explicitly per the Sprint 3.5 schema).
	OpenedAt time.Time
	// ClosedAt/CloseReason — set exactly once at closure; audit trail.
	ClosedAt    *time.Time
	CloseReason string
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// IsOpen reports whether the cluster still absorbs trends.
func (c *TrendCluster) IsOpen() bool {
	return c.State == "" || c.State == ClusterActive
}

// StaleAfter reports whether the cluster has had no activity for
// longer than d at `now`.
func (c *TrendCluster) StaleAfter(d time.Duration, now time.Time) bool {
	return now.Sub(c.UpdatedAt) > d
}

// Close transitions the cluster to a terminal state. Idempotent: a
// closed cluster keeps its first closure.
func (c *TrendCluster) Close(state State, reason string, now time.Time) bool {
	if !c.IsOpen() {
		return false
	}
	c.State = state
	c.CloseReason = reason
	closedAt := now.UTC()
	c.ClosedAt = &closedAt
	c.UpdatedAt = closedAt
	return true
}

// Absorb folds one trend into the cluster.
func (c *TrendCluster) Absorb(trendID, trendType string, confidence float64, now time.Time) {
	c.TrendIDs = append(c.TrendIDs, trendID)
	seen := false
	for _, t := range c.TrendTypes {
		if t == trendType {
			seen = true
			break
		}
	}
	if !seen {
		c.TrendTypes = append(c.TrendTypes, trendType)
	}
	if confidence > c.Confidence {
		c.Confidence = confidence
	}
	c.UpdatedAt = now
}
