// Package postgres — Nexus persistence (nexus schema).
//
// Tables (migrations/sql/0001): nexus.agents, nexus.agent_memories,
// nexus.agent_drafts, nexus.agent_publications. The five official
// agents are migration SEEDS — code never hardcodes them.
package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// Connect builds the pool and pings.
func Connect(ctx context.Context, url string) (*pgxpool.Pool, error) {
	pool, err := pgxpool.New(ctx, url)
	if err != nil {
		return nil, fmt.Errorf("postgres: connect: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("postgres: ping: %w", err)
	}
	return pool, nil
}

// ---- AgentRepo ---------------------------------------------------------------

type AgentRepo struct{ pool *pgxpool.Pool }

func NewAgentRepo(pool *pgxpool.Pool) *AgentRepo { return &AgentRepo{pool: pool} }

const agentColumns = `id, name, avatar, bio, active, specialty,
	trend_types, posting_rules, rag_sources, system_context,
	created_at, updated_at`

func (r *AgentRepo) List(ctx context.Context) ([]agent.Agent, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT `+agentColumns+` FROM nexus.agents ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("agents list: %w", err)
	}
	defer rows.Close()
	return scanAgents(rows)
}

func (r *AgentRepo) ListActive(ctx context.Context) ([]agent.Agent, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT `+agentColumns+` FROM nexus.agents WHERE active ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("agents list active: %w", err)
	}
	defer rows.Close()
	return scanAgents(rows)
}

func (r *AgentRepo) Get(ctx context.Context, id uuid.UUID) (agent.Agent, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+agentColumns+` FROM nexus.agents WHERE id = $1`, id)
	a, err := scanAgent(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return agent.Agent{}, ports.ErrNotFound
	}
	return a, err
}

func (r *AgentRepo) Create(ctx context.Context, a agent.Agent) error {
	if err := a.Validate(); err != nil {
		return err
	}
	trendTypes, postingRules, ragSources, err := marshalAgentJSON(a)
	if err != nil {
		return err
	}
	_, err = r.pool.Exec(ctx, `
		INSERT INTO nexus.agents
			(id, name, avatar, bio, active, specialty, trend_types,
			 posting_rules, rag_sources, system_context, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now(), now())`,
		a.ID, a.Name, a.Avatar, a.Bio, a.Active, a.Specialty,
		trendTypes, postingRules, ragSources, a.SystemContext,
	)
	if err != nil {
		return fmt.Errorf("agents create: %w", err)
	}
	return nil
}

func (r *AgentRepo) Update(ctx context.Context, a agent.Agent) error {
	if err := a.Validate(); err != nil {
		return err
	}
	trendTypes, postingRules, ragSources, err := marshalAgentJSON(a)
	if err != nil {
		return err
	}
	tag, err := r.pool.Exec(ctx, `
		UPDATE nexus.agents SET
			name=$2, avatar=$3, bio=$4, active=$5, specialty=$6,
			trend_types=$7, posting_rules=$8, rag_sources=$9,
			system_context=$10, updated_at=now()
		WHERE id = $1`,
		a.ID, a.Name, a.Avatar, a.Bio, a.Active, a.Specialty,
		trendTypes, postingRules, ragSources, a.SystemContext,
	)
	if err != nil {
		return fmt.Errorf("agents update: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ports.ErrNotFound
	}
	return nil
}

func (r *AgentRepo) SetActive(ctx context.Context, id uuid.UUID, active bool) error {
	tag, err := r.pool.Exec(ctx,
		`UPDATE nexus.agents SET active=$2, updated_at=now() WHERE id=$1`,
		id, active)
	if err != nil {
		return fmt.Errorf("agents set active: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ports.ErrNotFound
	}
	return nil
}

func marshalAgentJSON(a agent.Agent) ([]byte, []byte, []byte, error) {
	trendTypes, err := json.Marshal(a.TrendTypes)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("agents: marshal trend_types: %w", err)
	}
	rules := a.PostingRules
	if rules == nil {
		rules = map[string]any{}
	}
	postingRules, err := json.Marshal(rules)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("agents: marshal posting_rules: %w", err)
	}
	sources := a.RAGSources
	if sources == nil {
		sources = []string{}
	}
	ragSources, err := json.Marshal(sources)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("agents: marshal rag_sources: %w", err)
	}
	return trendTypes, postingRules, ragSources, nil
}

type rowScanner interface{ Scan(dest ...any) error }

func scanAgent(row rowScanner) (agent.Agent, error) {
	var (
		a            agent.Agent
		trendTypes   []byte
		postingRules []byte
		ragSources   []byte
	)
	err := row.Scan(
		&a.ID, &a.Name, &a.Avatar, &a.Bio, &a.Active, &a.Specialty,
		&trendTypes, &postingRules, &ragSources, &a.SystemContext,
		&a.CreatedAt, &a.UpdatedAt,
	)
	if err != nil {
		return agent.Agent{}, err
	}
	if err := json.Unmarshal(trendTypes, &a.TrendTypes); err != nil {
		return agent.Agent{}, fmt.Errorf("agents: trend_types: %w", err)
	}
	if err := json.Unmarshal(postingRules, &a.PostingRules); err != nil {
		return agent.Agent{}, fmt.Errorf("agents: posting_rules: %w", err)
	}
	if err := json.Unmarshal(ragSources, &a.RAGSources); err != nil {
		return agent.Agent{}, fmt.Errorf("agents: rag_sources: %w", err)
	}
	return a, nil
}

func scanAgents(rows pgx.Rows) ([]agent.Agent, error) {
	out := make([]agent.Agent, 0, 8)
	for rows.Next() {
		a, err := scanAgent(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// ---- MemoryRepo ----------------------------------------------------------------

type MemoryRepo struct{ pool *pgxpool.Pool }

func NewMemoryRepo(pool *pgxpool.Pool) *MemoryRepo { return &MemoryRepo{pool: pool} }

func (r *MemoryRepo) Save(ctx context.Context, m memory.Memory) error {
	if err := m.Validate(); err != nil {
		return err
	}
	kind := m.Kind
	if kind == "" {
		kind = memory.KindObservation
	}
	var clusterID any
	if m.ClusterID != uuid.Nil {
		clusterID = m.ClusterID
	}
	_, err := r.pool.Exec(ctx, `
		INSERT INTO nexus.agent_memories
			(id, agent_id, match_id, trend_id, cluster_type, cluster_id,
			 kind, summary, narrative, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
		m.ID, m.AgentID, m.MatchID, m.TrendID, m.ClusterType, clusterID,
		string(kind), m.Summary, m.Narrative, m.CreatedAt,
	)
	if err != nil {
		return fmt.Errorf("memories save: %w", err)
	}
	return nil
}

func (r *MemoryRepo) Recent(
	ctx context.Context, agentID uuid.UUID, matchID string, limit int,
) ([]memory.Memory, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, agent_id, match_id, trend_id, cluster_type,
		       COALESCE(cluster_id, '00000000-0000-0000-0000-000000000000'::uuid),
		       kind, summary, narrative, created_at
		FROM nexus.agent_memories
		WHERE agent_id = $1 AND match_id = $2
		ORDER BY created_at DESC LIMIT $3`,
		agentID, matchID, limit)
	if err != nil {
		return nil, fmt.Errorf("memories recent: %w", err)
	}
	defer rows.Close()
	return scanMemories(rows, limit)
}

// Related — same-agent, same-story-cluster memories across matches
// (Sprint 3 narrative continuity).
func (r *MemoryRepo) Related(
	ctx context.Context, agentID uuid.UUID, clusterType string, limit int,
) ([]memory.Memory, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, agent_id, match_id, trend_id, cluster_type,
		       COALESCE(cluster_id, '00000000-0000-0000-0000-000000000000'::uuid),
		       kind, summary, narrative, created_at
		FROM nexus.agent_memories
		WHERE agent_id = $1 AND cluster_type = $2
		ORDER BY created_at DESC LIMIT $3`,
		agentID, clusterType, limit)
	if err != nil {
		return nil, fmt.Errorf("memories related: %w", err)
	}
	defer rows.Close()
	return scanMemories(rows, limit)
}

// RecentPublications — Sprint 4: publication memories on one story.
func (r *MemoryRepo) RecentPublications(
	ctx context.Context, agentID uuid.UUID, clusterID uuid.UUID, limit int,
) ([]memory.Memory, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, agent_id, match_id, trend_id, cluster_type,
		       COALESCE(cluster_id, '00000000-0000-0000-0000-000000000000'::uuid),
		       kind, summary, narrative, created_at
		FROM nexus.agent_memories
		WHERE agent_id = $1 AND cluster_id = $2 AND kind = 'publication'
		ORDER BY created_at DESC LIMIT $3`,
		agentID, clusterID, limit)
	if err != nil {
		return nil, fmt.Errorf("memories recent_publications: %w", err)
	}
	defer rows.Close()
	return scanMemories(rows, limit)
}

func scanMemories(rows pgx.Rows, limit int) ([]memory.Memory, error) {
	out := make([]memory.Memory, 0, limit)
	for rows.Next() {
		var m memory.Memory
		var kind string
		if err := rows.Scan(&m.ID, &m.AgentID, &m.MatchID, &m.TrendID,
			&m.ClusterType, &m.ClusterID, &kind, &m.Summary,
			&m.Narrative, &m.CreatedAt); err != nil {
			return nil, err
		}
		m.Kind = memory.Kind(kind)
		out = append(out, m)
	}
	return out, rows.Err()
}

// ---- DraftRepo -------------------------------------------------------------------

type DraftRepo struct{ pool *pgxpool.Pool }

func NewDraftRepo(pool *pgxpool.Pool) *DraftRepo { return &DraftRepo{pool: pool} }

func (r *DraftRepo) Save(ctx context.Context, d draft.Draft) error {
	if err := d.Validate(); err != nil {
		return err
	}
	highlights, err := json.Marshal(d.Highlights)
	if err != nil {
		return fmt.Errorf("drafts: marshal highlights: %w", err)
	}
	charts, err := json.Marshal(d.Charts)
	if err != nil {
		return fmt.Errorf("drafts: marshal charts: %w", err)
	}
	metadata, err := json.Marshal(d.Metadata)
	if err != nil {
		return fmt.Errorf("drafts: marshal metadata: %w", err)
	}
	_, err = r.pool.Exec(ctx, `
		INSERT INTO nexus.agent_drafts
			(id, agent_id, trend_id, match_id, title, summary,
			 highlights, charts, metadata, status, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		d.ID, d.AgentID, d.TrendID, d.MatchID, d.Title, d.Summary,
		highlights, charts, metadata, string(d.Status), d.CreatedAt,
	)
	if err != nil {
		return fmt.Errorf("drafts save: %w", err)
	}
	return nil
}

// ---- PublicationRepo ---------------------------------------------------------------

type PublicationRepo struct{ pool *pgxpool.Pool }

func NewPublicationRepo(pool *pgxpool.Pool) *PublicationRepo {
	return &PublicationRepo{pool: pool}
}

func (r *PublicationRepo) RecordCandidate(ctx context.Context, c ports.PublicationCandidate) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO nexus.agent_publications
			(id, draft_id, agent_id, trend_id, queue, priority, status, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,'queued',$7)`,
		uuid.New(), c.DraftID, c.AgentID, c.TrendID, c.Queue, c.Priority,
		time.Now().UTC(),
	)
	if err != nil {
		return fmt.Errorf("publications record: %w", err)
	}
	return nil
}

var (
	_ ports.AgentRepository       = (*AgentRepo)(nil)
	_ ports.MemoryRepository      = (*MemoryRepo)(nil)
	_ ports.DraftRepository       = (*DraftRepo)(nil)
	_ ports.PublicationRepository = (*PublicationRepo)(nil)
)
