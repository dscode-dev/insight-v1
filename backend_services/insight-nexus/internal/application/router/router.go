// Package router — the Agent Router.
//
// Maps one Atlas trend to the agents that should communicate it.
// Routing is DATA-driven: each persisted agent declares the trend
// types/categories it consumes; the router matches against that
// configuration. Multiple agents may receive the same trend; a trend
// nobody consumes routes nowhere (and is counted, not lost silently).
package router

import (
	"context"

	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

type Router struct {
	agents ports.AgentRepository
	logger zerolog.Logger
}

func New(agents ports.AgentRepository, logger zerolog.Logger) *Router {
	return &Router{agents: agents, logger: logger}
}

// Route returns every ACTIVE agent whose configuration consumes this
// trend's type or category.
func (r *Router) Route(ctx context.Context, ev trend.Event) ([]agent.Agent, error) {
	active, err := r.agents.ListActive(ctx)
	if err != nil {
		return nil, err
	}
	matched := make([]agent.Agent, 0, 2)
	for _, a := range active {
		if a.Consumes(ev.TrendType, ev.Category) {
			matched = append(matched, a)
		}
	}
	if len(matched) == 0 {
		r.logger.Debug().
			Str("trend_type", ev.TrendType).
			Str("category", ev.Category).
			Msg("trend_unrouted")
	}
	return matched, nil
}
