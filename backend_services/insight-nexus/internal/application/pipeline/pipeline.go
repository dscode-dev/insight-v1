// Package pipeline — the Nexus communication-intelligence pipeline
// (Sprint 3):
//
//	Trend Consumer
//	    ↓
//	Agent Router            (who could communicate this?)
//	    ↓ (per agent)
//	Trend Clustering        (which story is this?)
//	    ↓
//	Publication Decision    (should communication exist at all?)
//	    ↓
//	Agent State Engine      (where is the agent in this story's arc?)
//	    ↓
//	Draft Evolution Engine  (what KIND of communication comes next?)
//	    ↓
//	Draft Generator         (structured draft + feed-readiness metadata)
//	    ↓
//	Publishing Queue
//
// Nexus no longer reacts to isolated trends: communication operates on
// clusters, every decision is persisted with its reasoning, and the
// same story evolves (initial → follow-up → confirmation →
// retrospective) instead of repeating.
package pipeline

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/application/agentstate"
	"github.com/konoha-labs/insight-nexus/internal/application/clustering"
	"github.com/konoha-labs/insight-nexus/internal/application/clusterlifecycle"
	"github.com/konoha-labs/insight-nexus/internal/application/contextbuilder"
	"github.com/konoha-labs/insight-nexus/internal/application/draftgen"
	"github.com/konoha-labs/insight-nexus/internal/application/evolution"
	"github.com/konoha-labs/insight-nexus/internal/application/matchsweep"
	"github.com/konoha-labs/insight-nexus/internal/application/publication"
	"github.com/konoha-labs/insight-nexus/internal/application/router"
	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	domainevolution "github.com/konoha-labs/insight-nexus/internal/domain/evolution"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// Metrics — the pipeline's observability seam.
type Metrics interface {
	TrendConsumed()
	DraftGenerated(agentName string)
	PublicationCandidate(agentName string)
}

type Pipeline struct {
	router     *router.Router
	clustering *clustering.Engine
	lifecycle  *clusterlifecycle.Engine
	sweep      *matchsweep.Engine
	decisions  *publication.Engine
	states     *agentstate.Engine
	evolution  *evolution.Engine
	builder    *contextbuilder.Builder
	gen        *draftgen.Generator

	drafts       ports.DraftRepository
	memories     ports.MemoryRepository
	pubs         ports.PublicationRepository
	decisionRepo ports.DecisionRepository
	queue        ports.DraftQueue
	metrics      Metrics
	logger       zerolog.Logger
	now          func() time.Time
}

type Deps struct {
	Router       *router.Router
	Clustering   *clustering.Engine
	Lifecycle    *clusterlifecycle.Engine
	Sweep        *matchsweep.Engine
	Decisions    *publication.Engine
	States       *agentstate.Engine
	Evolution    *evolution.Engine
	Builder      *contextbuilder.Builder
	Generator    *draftgen.Generator
	Drafts       ports.DraftRepository
	Memories     ports.MemoryRepository
	Publications ports.PublicationRepository
	DecisionRepo ports.DecisionRepository
	Queue        ports.DraftQueue
	Metrics      Metrics
	Logger       zerolog.Logger
	Now          func() time.Time
}

func New(d Deps) *Pipeline {
	now := d.Now
	if now == nil {
		now = time.Now
	}
	return &Pipeline{
		router:       d.Router,
		clustering:   d.Clustering,
		lifecycle:    d.Lifecycle,
		sweep:        d.Sweep,
		decisions:    d.Decisions,
		states:       d.States,
		evolution:    d.Evolution,
		builder:      d.Builder,
		gen:          d.Generator,
		drafts:       d.Drafts,
		memories:     d.Memories,
		pubs:         d.Publications,
		decisionRepo: d.DecisionRepo,
		queue:        d.Queue,
		metrics:      d.Metrics,
		logger:       d.Logger,
		now:          now,
	}
}

// Result — what one trend produced, for logging + tests.
type Result struct {
	RoutedAgents int
	Cluster      cluster.TrendCluster
	Decisions    []decision.PublicationDecision
	Drafts       []draft.Draft
}

// HandleTrend processes one consumed trend end-to-end.
func (p *Pipeline) HandleTrend(ctx context.Context, env trend.Envelope) (Result, error) {
	p.metrics.TrendConsumed()
	ev := env.Trend

	// Which story is this? (agent-independent — resolved once.)
	c, created, err := p.clustering.Assign(ctx, ev)
	if err != nil {
		return Result{}, fmt.Errorf("pipeline: cluster: %w", err)
	}

	// Sprint 3.5 — trend-driven narrative closure (confirmed completes
	// the story; failed + confidence collapse fails it). The closed
	// cluster still serves THIS tick (confirmation drafts); the next
	// trend opens a fresh one.
	if p.lifecycle != nil {
		if closed, _, lerr := p.lifecycle.EvaluateTrend(ctx, c, ev); lerr != nil {
			p.logger.Warn().Err(lerr).
				Str("cluster_id", c.ID.String()).
				Msg("cluster_lifecycle_evaluate_failed")
		} else {
			c = closed
		}
	}

	agents, err := p.router.Route(ctx, ev)
	if err != nil {
		return Result{}, fmt.Errorf("pipeline: route: %w", err)
	}

	result := Result{RoutedAgents: len(agents), Cluster: c}
	for _, a := range agents {
		d, dec, err := p.handleForAgent(ctx, env, a, c)
		if err != nil {
			// Agent isolation: log + continue. The trend is already
			// durable in Atlas; a per-agent failure is recoverable.
			p.logger.Error().Err(err).
				Str("agent", a.Name).
				Str("trend_id", ev.TrendID).
				Msg("pipeline_agent_failed")
			continue
		}
		result.Decisions = append(result.Decisions, dec)
		if d != nil {
			result.Drafts = append(result.Drafts, *d)
		}
	}
	// Sprint 3.5 — match end sweep: a terminal match marker closes
	// every lingering narrative on the match.
	if p.sweep != nil {
		if _, serr := p.sweep.MaybeSweep(ctx, ev); serr != nil {
			p.logger.Error().Err(serr).
				Str("match_id", ev.MatchID).
				Msg("match_sweep_failed")
		}
	}

	p.logger.Info().
		Str("trend_id", ev.TrendID).
		Str("trend_type", ev.TrendType).
		Str("cluster_type", string(c.ClusterType)).
		Bool("cluster_created", created).
		Int("routed_agents", result.RoutedAgents).
		Int("drafts", len(result.Drafts)).
		Bool("priority", env.Priority).
		Msg("trend_processed")
	return result, nil
}

// handleForAgent runs the decision → state → evolution → draft chain
// for one agent. Returns (draft|nil, decision, error).
func (p *Pipeline) handleForAgent(
	ctx context.Context, env trend.Envelope, a agent.Agent, c cluster.TrendCluster,
) (*draft.Draft, decision.PublicationDecision, error) {
	ev := env.Trend
	now := p.now().UTC()

	// 1. Publication Decision (agent history = drafts in this cluster).
	draftCount, err := p.evolution.CountForCluster(ctx, a.ID, c.ID)
	if err != nil {
		return nil, decision.PublicationDecision{}, fmt.Errorf("history: %w", err)
	}
	dec := p.decisions.Decide(publication.Inputs{
		AgentID:         a.ID,
		MatchID:         ev.MatchID,
		ClusterID:       c.ID,
		Trend:           ev,
		Priority:        env.Priority,
		AgentDraftCount: draftCount,
		Now:             now,
	})
	if err := p.decisionRepo.Record(ctx, dec); err != nil {
		return nil, dec, fmt.Errorf("record decision: %w", err)
	}

	if dec.Action == decision.ActionIgnore {
		return nil, dec, nil
	}

	// 2. Agent State (narrative arc — advanced for every non-ignore
	// action; even memory-only observation IS initial detection).
	st, err := p.states.Advance(ctx, a.ID, c, dec, ev)
	if err != nil {
		return nil, dec, fmt.Errorf("agent state: %w", err)
	}

	// saveMemory writes this tick's continuity line. Called AFTER the
	// draft context is built so a draft never cites itself as prior
	// continuity.
	saveMemory := func() error {
		m := memory.Memory{
			ID:          uuid.New(),
			AgentID:     a.ID,
			MatchID:     ev.MatchID,
			TrendID:     ev.TrendID,
			ClusterType: string(c.ClusterType),
			Summary:     memorySummary(ev),
			CreatedAt:   now,
		}
		return p.memories.Save(ctx, m)
	}

	if !dec.Action.Drafts() {
		if err := saveMemory(); err != nil {
			return nil, dec, fmt.Errorf("save memory: %w", err)
		}
		return nil, dec, nil
	}

	// 3. Draft Evolution (what kind of communication comes next?).
	class, err := p.evolution.Classify(ctx, a.ID, c.ID, st.Current, ev)
	if err != nil {
		return nil, dec, fmt.Errorf("evolution: %w", err)
	}

	// 4. Context (recent + related memories — prior observations only).
	dc, err := p.builder.Build(ctx, a, ev, env.Priority, string(c.ClusterType))
	if err != nil {
		return nil, dec, fmt.Errorf("build context: %w", err)
	}
	dc.ClusterID = c.ID
	dc.Action = string(dec.Action)
	dc.Priority = string(dec.Priority)
	dc.AgentState = string(st.Current)
	dc.DraftType = string(class.DraftType)
	dc.Sequence = class.Sequence

	// 5. Structured draft + evolution record + memory.
	d := p.gen.Generate(dc)
	if err := d.Validate(); err != nil {
		return nil, dec, fmt.Errorf("invalid draft: %w", err)
	}
	if err := p.drafts.Save(ctx, d); err != nil {
		return nil, dec, fmt.Errorf("save draft: %w", err)
	}
	p.metrics.DraftGenerated(a.Name)
	if err := p.evolution.Record(ctx, a.ID, c.ID, d.ID, ev.MatchID, class); err != nil {
		return nil, dec, fmt.Errorf("record evolution: %w", err)
	}
	// Sprint 3.5 — a RETROSPECTIVE draft completes the narrative.
	if p.lifecycle != nil && class.DraftType == domainevolution.Retrospective {
		if _, _, lerr := p.lifecycle.CompleteOnRetrospective(ctx, c); lerr != nil {
			p.logger.Warn().Err(lerr).
				Str("cluster_id", c.ID.String()).
				Msg("cluster_retrospective_close_failed")
		}
	}
	if err := saveMemory(); err != nil {
		return nil, dec, fmt.Errorf("save memory: %w", err)
	}

	// 6. Durable candidate, then the publishing queue.
	//
	// ORDER MATTERS. The candidate row is written FIRST: it is what the
	// console lists as "queued". Enqueuing first would open a window where
	// the publish worker could pick the draft up, publish it, and update a
	// candidate row that does not exist yet.
	priority := dec.Action == decision.ActionHighPriority ||
		dec.Action == decision.ActionGlobal
	if err := p.pubs.RecordCandidate(ctx, ports.PublicationCandidate{
		DraftID:  d.ID,
		AgentID:  a.ID,
		TrendID:  ev.TrendID,
		Queue:    a.QueueName(),
		Priority: priority,
	}); err != nil {
		return nil, dec, fmt.Errorf("record candidate: %w", err)
	}
	// The handoff. Publication itself runs in publishworker, off this
	// goroutine: an LLM call takes up to one timeout per provider, and
	// doing it here stalled the trend stream for every other agent.
	//
	// This is the last durable write before the trend is acknowledged, so
	// a crash after it loses nothing — the queue entry is unacked and gets
	// redelivered to the worker.
	if err := p.queue.Enqueue(ctx, a.QueueName(), ports.QueuedDraft{
		Draft:    d,
		Context:  dc,
		Decision: dec,
		Priority: priority,
	}); err != nil {
		return nil, dec, fmt.Errorf("enqueue: %w", err)
	}
	p.metrics.PublicationCandidate(a.Name)
	return &d, dec, nil
}

// memorySummary — the deterministic continuity line. Built from
// Atlas's interpretation, never generated.
func memorySummary(ev trend.Event) string {
	st := ev.LifecycleState
	if st == "" {
		st = "observed"
	}
	meaning := ev.Meaning
	if meaning == "" {
		meaning = ev.TrendType
	}
	return fmt.Sprintf("%s: %s (%s)", ev.TrendType, meaning, st)
}
