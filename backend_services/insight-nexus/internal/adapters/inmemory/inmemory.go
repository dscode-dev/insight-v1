// Package inmemory — in-process implementations of every Nexus port.
// Used by the test suite and local development without Postgres/Redis.
// Concurrency-safe; semantics mirror the production adapters.
package inmemory

import (
	"context"
	"sort"
	"sync"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/evolution"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/state"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// ---- AgentRepository --------------------------------------------------------

type AgentRepo struct {
	mu     sync.RWMutex
	agents map[uuid.UUID]agent.Agent
}

func NewAgentRepo() *AgentRepo {
	return &AgentRepo{agents: map[uuid.UUID]agent.Agent{}}
}

func (r *AgentRepo) List(_ context.Context) ([]agent.Agent, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]agent.Agent, 0, len(r.agents))
	for _, a := range r.agents {
		out = append(out, a)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

func (r *AgentRepo) ListActive(ctx context.Context) ([]agent.Agent, error) {
	all, _ := r.List(ctx)
	out := make([]agent.Agent, 0, len(all))
	for _, a := range all {
		if a.Active {
			out = append(out, a)
		}
	}
	return out, nil
}

func (r *AgentRepo) Get(_ context.Context, id uuid.UUID) (agent.Agent, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	a, ok := r.agents[id]
	if !ok {
		return agent.Agent{}, ports.ErrNotFound
	}
	return a, nil
}

func (r *AgentRepo) Create(_ context.Context, a agent.Agent) error {
	if err := a.Validate(); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.agents[a.ID]; exists {
		return ports.ErrDuplicate
	}
	r.agents[a.ID] = a
	return nil
}

func (r *AgentRepo) Update(_ context.Context, a agent.Agent) error {
	if err := a.Validate(); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.agents[a.ID]; !exists {
		return ports.ErrNotFound
	}
	r.agents[a.ID] = a
	return nil
}

func (r *AgentRepo) SetActive(_ context.Context, id uuid.UUID, active bool) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	a, ok := r.agents[id]
	if !ok {
		return ports.ErrNotFound
	}
	a.Active = active
	r.agents[id] = a
	return nil
}

// ---- MemoryRepository -------------------------------------------------------

type MemoryRepo struct {
	mu       sync.RWMutex
	memories []memory.Memory
}

func NewMemoryRepo() *MemoryRepo { return &MemoryRepo{} }

func (r *MemoryRepo) Save(_ context.Context, m memory.Memory) error {
	if err := m.Validate(); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.memories = append(r.memories, m)
	return nil
}

func (r *MemoryRepo) Recent(
	_ context.Context, agentID uuid.UUID, matchID string, limit int,
) ([]memory.Memory, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	matched := make([]memory.Memory, 0, limit)
	for _, m := range r.memories {
		if m.AgentID == agentID && m.MatchID == matchID {
			matched = append(matched, m)
		}
	}
	// Newest first.
	sort.Slice(matched, func(i, j int) bool {
		return matched[i].CreatedAt.After(matched[j].CreatedAt)
	})
	if len(matched) > limit {
		matched = matched[:limit]
	}
	return matched, nil
}

// ---- DraftRepository --------------------------------------------------------

type DraftRepo struct {
	mu     sync.RWMutex
	drafts []draft.Draft
}

func NewDraftRepo() *DraftRepo { return &DraftRepo{} }

func (r *DraftRepo) Save(_ context.Context, d draft.Draft) error {
	if err := d.Validate(); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.drafts = append(r.drafts, d)
	return nil
}

func (r *DraftRepo) All() []draft.Draft {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]draft.Draft, len(r.drafts))
	copy(out, r.drafts)
	return out
}

// ---- PublicationRepository ----------------------------------------------------

type PublicationRepo struct {
	mu         sync.RWMutex
	candidates []ports.PublicationCandidate
}

func NewPublicationRepo() *PublicationRepo { return &PublicationRepo{} }

func (r *PublicationRepo) RecordCandidate(_ context.Context, c ports.PublicationCandidate) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.candidates = append(r.candidates, c)
	return nil
}

func (r *PublicationRepo) All() []ports.PublicationCandidate {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]ports.PublicationCandidate, len(r.candidates))
	copy(out, r.candidates)
	return out
}

// ---- DraftQueue ----------------------------------------------------------------

type Queue struct {
	mu     sync.RWMutex
	queues map[string][]draft.Draft
}

func NewQueue() *Queue { return &Queue{queues: map[string][]draft.Draft{}} }

func (q *Queue) Enqueue(_ context.Context, queueName string, d draft.Draft, _ bool) error {
	q.mu.Lock()
	defer q.mu.Unlock()
	q.queues[queueName] = append(q.queues[queueName], d)
	return nil
}

func (q *Queue) Depth(_ context.Context, queueName string) (int64, error) {
	q.mu.RLock()
	defer q.mu.RUnlock()
	return int64(len(q.queues[queueName])), nil
}

var (
	_ ports.AgentRepository       = (*AgentRepo)(nil)
	_ ports.MemoryRepository      = (*MemoryRepo)(nil)
	_ ports.DraftRepository       = (*DraftRepo)(nil)
	_ ports.PublicationRepository = (*PublicationRepo)(nil)
	_ ports.DraftQueue            = (*Queue)(nil)
)

// ---- Sprint 3: Related memories ------------------------------------------------

func (r *MemoryRepo) Related(
	_ context.Context, agentID uuid.UUID, clusterType string, limit int,
) ([]memory.Memory, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	matched := make([]memory.Memory, 0, limit)
	for _, m := range r.memories {
		if m.AgentID == agentID && m.ClusterType == clusterType {
			matched = append(matched, m)
		}
	}
	sort.Slice(matched, func(i, j int) bool {
		return matched[i].CreatedAt.After(matched[j].CreatedAt)
	})
	if len(matched) > limit {
		matched = matched[:limit]
	}
	return matched, nil
}

// RecentPublications — Sprint 4: the agent's publication memories on
// one concrete story instance, newest first.
func (r *MemoryRepo) RecentPublications(
	_ context.Context, agentID uuid.UUID, clusterID uuid.UUID, limit int,
) ([]memory.Memory, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	matched := make([]memory.Memory, 0, limit)
	for _, m := range r.memories {
		if m.AgentID == agentID && m.ClusterID == clusterID &&
			m.Kind == memory.KindPublication {
			matched = append(matched, m)
		}
	}
	sort.Slice(matched, func(i, j int) bool {
		return matched[i].CreatedAt.After(matched[j].CreatedAt)
	})
	if len(matched) > limit {
		matched = matched[:limit]
	}
	return matched, nil
}

// ---- ClusterRepository ----------------------------------------------------------

type ClusterRepo struct {
	mu       sync.RWMutex
	clusters map[uuid.UUID]cluster.TrendCluster
	order    []uuid.UUID
}

func NewClusterRepo() *ClusterRepo {
	return &ClusterRepo{clusters: map[uuid.UUID]cluster.TrendCluster{}}
}

func (r *ClusterRepo) GetActive(
	_ context.Context, matchID string, clusterType cluster.Type,
) (cluster.TrendCluster, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	// Newest open cluster wins (closed clusters are never reused —
	// Sprint 3.5 reopen behaviour).
	for i := len(r.order) - 1; i >= 0; i-- {
		c := r.clusters[r.order[i]]
		if c.MatchID == matchID && c.ClusterType == clusterType && c.IsOpen() {
			return c, nil
		}
	}
	return cluster.TrendCluster{}, ports.ErrNotFound
}

func (r *ClusterRepo) Save(_ context.Context, c cluster.TrendCluster) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.clusters[c.ID]; !exists {
		r.order = append(r.order, c.ID)
	}
	r.clusters[c.ID] = c
	return nil
}

func (r *ClusterRepo) ListActiveByMatch(
	_ context.Context, matchID string,
) ([]cluster.TrendCluster, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]cluster.TrendCluster, 0, 4)
	for _, id := range r.order {
		c := r.clusters[id]
		if c.MatchID == matchID && c.IsOpen() {
			out = append(out, c)
		}
	}
	return out, nil
}

func (r *ClusterRepo) List(_ context.Context, limit int) ([]cluster.TrendCluster, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]cluster.TrendCluster, 0, limit)
	for i := len(r.order) - 1; i >= 0 && len(out) < limit; i-- {
		out = append(out, r.clusters[r.order[i]])
	}
	return out, nil
}

// ---- DecisionRepository ------------------------------------------------------------

type DecisionRepo struct {
	mu        sync.RWMutex
	decisions []decision.PublicationDecision
}

func NewDecisionRepo() *DecisionRepo { return &DecisionRepo{} }

func (r *DecisionRepo) Record(_ context.Context, d decision.PublicationDecision) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.decisions = append(r.decisions, d)
	return nil
}

func (r *DecisionRepo) List(_ context.Context, limit int) ([]decision.PublicationDecision, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]decision.PublicationDecision, 0, limit)
	for i := len(r.decisions) - 1; i >= 0 && len(out) < limit; i-- {
		out = append(out, r.decisions[i])
	}
	return out, nil
}

// ---- AgentStateRepository ------------------------------------------------------------

type AgentStateRepo struct {
	mu     sync.RWMutex
	states map[string]state.AgentState // key: agent|match|cluster
	order  []string
}

func NewAgentStateRepo() *AgentStateRepo {
	return &AgentStateRepo{states: map[string]state.AgentState{}}
}

func stateKey(agentID uuid.UUID, matchID string, clusterID uuid.UUID) string {
	return agentID.String() + "|" + matchID + "|" + clusterID.String()
}

func (r *AgentStateRepo) Get(
	_ context.Context, agentID uuid.UUID, matchID string, clusterID uuid.UUID,
) (state.AgentState, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	s, ok := r.states[stateKey(agentID, matchID, clusterID)]
	if !ok {
		return state.AgentState{}, ports.ErrNotFound
	}
	return s, nil
}

func (r *AgentStateRepo) Save(_ context.Context, s state.AgentState) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := stateKey(s.AgentID, s.MatchID, s.ClusterID)
	if _, exists := r.states[key]; !exists {
		r.order = append(r.order, key)
	}
	r.states[key] = s
	return nil
}

func (r *AgentStateRepo) ListActiveByMatch(
	_ context.Context, matchID string,
) ([]state.AgentState, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]state.AgentState, 0, 8)
	for _, key := range r.order {
		s := r.states[key]
		if s.MatchID != matchID {
			continue
		}
		switch s.Current {
		case state.Observing, state.Tracking, state.Alerting:
			out = append(out, s)
		}
	}
	return out, nil
}

func (r *AgentStateRepo) ListByAgent(
	_ context.Context, agentID uuid.UUID, limit int,
) ([]state.AgentState, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]state.AgentState, 0, limit)
	for i := len(r.order) - 1; i >= 0 && len(out) < limit; i-- {
		s := r.states[r.order[i]]
		if s.AgentID == agentID {
			out = append(out, s)
		}
	}
	return out, nil
}

// ---- EvolutionRepository ------------------------------------------------------------

type EvolutionRepo struct {
	mu      sync.RWMutex
	records []evolution.Record
}

func NewEvolutionRepo() *EvolutionRepo { return &EvolutionRepo{} }

func (r *EvolutionRepo) Record(_ context.Context, rec evolution.Record) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.records = append(r.records, rec)
	return nil
}

func (r *EvolutionRepo) CountForCluster(
	_ context.Context, agentID uuid.UUID, clusterID uuid.UUID,
) (int, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	count := 0
	for _, rec := range r.records {
		if rec.AgentID == agentID && rec.ClusterID == clusterID {
			count++
		}
	}
	return count, nil
}

func (r *EvolutionRepo) ListByCluster(
	_ context.Context, clusterID uuid.UUID, limit int,
) ([]evolution.Record, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]evolution.Record, 0, limit)
	for _, rec := range r.records {
		if rec.ClusterID == clusterID {
			out = append(out, rec)
			if len(out) >= limit {
				break
			}
		}
	}
	return out, nil
}

func (r *EvolutionRepo) List(_ context.Context, limit int) ([]evolution.Record, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]evolution.Record, 0, limit)
	for i := len(r.records) - 1; i >= 0 && len(out) < limit; i-- {
		out = append(out, r.records[i])
	}
	return out, nil
}

var (
	_ ports.ClusterRepository    = (*ClusterRepo)(nil)
	_ ports.DecisionRepository   = (*DecisionRepo)(nil)
	_ ports.AgentStateRepository = (*AgentStateRepo)(nil)
	_ ports.EvolutionRepository  = (*EvolutionRepo)(nil)
)
