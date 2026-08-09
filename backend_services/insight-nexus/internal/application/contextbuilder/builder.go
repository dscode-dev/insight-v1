// Package contextbuilder — assembles everything one agent knows when
// drafting about one story: the trend itself (Atlas's evaluated +
// interpreted contract, consumed verbatim), the agent's recent
// memories for the match, the agent's RELATED memories for the story
// cluster across matches (Sprint 3 — narrative continuity), and the
// communication-intelligence context the pipeline resolved (cluster,
// decision, state, evolution).
package contextbuilder

import (
	"context"

	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// MemoryWindow — how many recent/related memories the context carries.
const MemoryWindow = 10

// DraftContext is the complete input to the draft generator.
//
// The struct itself now lives in the domain (`draft.Context`) so the
// publishing queue can carry it across the process boundary — see the note
// there. This alias keeps every existing caller and test unchanged.
type DraftContext = draft.Context

// MetricsRecorder — the builder's observability seam.
type MetricsRecorder interface {
	MemoryHit()
	MemoryMiss()
}

type Builder struct {
	memories ports.MemoryRepository
	metrics  MetricsRecorder
}

func New(memories ports.MemoryRepository, metrics MetricsRecorder) *Builder {
	return &Builder{memories: memories, metrics: metrics}
}

// Build assembles the memory context. The pipeline fills the
// communication-intelligence fields afterwards.
func (b *Builder) Build(
	ctx context.Context, a agent.Agent, ev trend.Event, priority bool, clusterType string,
) (DraftContext, error) {
	recent, err := b.memories.Recent(ctx, a.ID, ev.MatchID, MemoryWindow)
	if err != nil {
		return DraftContext{}, err
	}
	var related []memory.Memory
	if clusterType != "" {
		related, err = b.memories.Related(ctx, a.ID, clusterType, MemoryWindow)
		if err != nil {
			return DraftContext{}, err
		}
	}
	hit := len(recent) > 0 || len(related) > 0
	if b.metrics != nil {
		if hit {
			b.metrics.MemoryHit()
		} else {
			b.metrics.MemoryMiss()
		}
	}
	return DraftContext{
		Agent:          a,
		Trend:          ev,
		StreamPriority: priority,
		Memories:       recent,
		Related:        related,
		MemoryHit:      hit,
		ClusterType:    clusterType,
	}, nil
}
