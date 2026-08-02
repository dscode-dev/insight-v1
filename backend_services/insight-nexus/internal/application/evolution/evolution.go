// Package evolution — the Draft Evolution Engine.
//
// Classifies WHERE each new draft sits in its story's narrative arc so
// communication evolves instead of repeating:
//
//	first draft in cluster        → INITIAL_OBSERVATION
//	story develops                → FOLLOW_UP
//	trend confirmed               → CONFIRMATION
//	post-event (retrospective)    → RETROSPECTIVE
//
// Each classification is persisted with its 1-based sequence position
// in the cluster's narrative.
package evolution

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	domainevolution "github.com/konoha-labs/insight-nexus/internal/domain/evolution"
	"github.com/konoha-labs/insight-nexus/internal/domain/state"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

var draftEvolutionTotal = promauto.NewCounterVec(prometheus.CounterOpts{
	Name: "draft_evolution_total",
	Help: "Draft evolution classifications, by draft type.",
}, []string{"draft_type"})

type Engine struct {
	records ports.EvolutionRepository
	now     func() time.Time
}

func New(records ports.EvolutionRepository, now func() time.Time) *Engine {
	if now == nil {
		now = time.Now
	}
	return &Engine{records: records, now: now}
}

// Classification — the draft's narrative position before generation.
type Classification struct {
	DraftType domainevolution.DraftType
	Sequence  int // 1-based position in the cluster narrative
}

// CountForCluster — how many drafts the agent already produced in the
// cluster. Exposed for the publication engine's agent-history input.
func (e *Engine) CountForCluster(
	ctx context.Context, agentID uuid.UUID, clusterID uuid.UUID,
) (int, error) {
	return e.records.CountForCluster(ctx, agentID, clusterID)
}

// Classify resolves the draft type for the agent's NEXT draft in the
// cluster. Deterministic precedence: retrospective state → confirmed
// lifecycle → first draft → follow-up.
func (e *Engine) Classify(
	ctx context.Context,
	agentID uuid.UUID,
	clusterID uuid.UUID,
	agentState state.State,
	ev trend.Event,
) (Classification, error) {
	count, err := e.records.CountForCluster(ctx, agentID, clusterID)
	if err != nil {
		return Classification{}, fmt.Errorf("evolution: count: %w", err)
	}
	sequence := count + 1

	var draftType domainevolution.DraftType
	switch {
	case agentState == state.Retrospective:
		draftType = domainevolution.Retrospective
	case ev.LifecycleState == "confirmed":
		draftType = domainevolution.Confirmation
	case count == 0:
		draftType = domainevolution.InitialObservation
	default:
		draftType = domainevolution.FollowUp
	}
	return Classification{DraftType: draftType, Sequence: sequence}, nil
}

// Record persists one evolution step after the draft was generated.
func (e *Engine) Record(
	ctx context.Context,
	agentID uuid.UUID,
	clusterID uuid.UUID,
	draftID uuid.UUID,
	matchID string,
	c Classification,
) error {
	rec := domainevolution.Record{
		ID:        uuid.New(),
		AgentID:   agentID,
		ClusterID: clusterID,
		DraftID:   draftID,
		MatchID:   matchID,
		DraftType: c.DraftType,
		Sequence:  c.Sequence,
		CreatedAt: e.now().UTC(),
	}
	if err := e.records.Record(ctx, rec); err != nil {
		return fmt.Errorf("evolution: record: %w", err)
	}
	draftEvolutionTotal.WithLabelValues(string(c.DraftType)).Inc()
	return nil
}
