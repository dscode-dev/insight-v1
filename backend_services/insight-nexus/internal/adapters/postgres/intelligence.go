// Sprint 3 persistence — clusters, decisions, agent states, evolution.
package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/konoha-labs/insight-nexus/internal/domain/cluster"
	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	"github.com/konoha-labs/insight-nexus/internal/domain/evolution"
	"github.com/konoha-labs/insight-nexus/internal/domain/state"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// ---- ClusterRepo ----------------------------------------------------------------

type ClusterRepo struct{ pool *pgxpool.Pool }

func NewClusterRepo(pool *pgxpool.Pool) *ClusterRepo { return &ClusterRepo{pool: pool} }

const clusterColumns = `id, match_id, cluster_type, trend_ids, trend_types,
	confidence, state, opened_at, closed_at, close_reason,
	created_at, updated_at`

func (r *ClusterRepo) GetActive(
	ctx context.Context, matchID string, clusterType cluster.Type,
) (cluster.TrendCluster, error) {
	// Closed clusters are never reused: only ACTIVE rows resolve, and
	// the newest open one wins.
	row := r.pool.QueryRow(ctx, `
		SELECT `+clusterColumns+`
		FROM nexus.trend_clusters
		WHERE match_id = $1 AND cluster_type = $2 AND state = 'ACTIVE'
		ORDER BY opened_at DESC LIMIT 1`,
		matchID, string(clusterType))
	c, err := scanCluster(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return cluster.TrendCluster{}, ports.ErrNotFound
	}
	return c, err
}

func (r *ClusterRepo) Save(ctx context.Context, c cluster.TrendCluster) error {
	trendIDs, err := json.Marshal(c.TrendIDs)
	if err != nil {
		return fmt.Errorf("clusters: marshal trend_ids: %w", err)
	}
	trendTypes, err := json.Marshal(c.TrendTypes)
	if err != nil {
		return fmt.Errorf("clusters: marshal trend_types: %w", err)
	}
	st := string(c.State)
	if st == "" {
		st = string(cluster.ClusterActive)
	}
	openedAt := c.OpenedAt
	if openedAt.IsZero() {
		openedAt = c.CreatedAt
	}
	_, err = r.pool.Exec(ctx, `
		INSERT INTO nexus.trend_clusters
			(id, match_id, cluster_type, trend_ids, trend_types,
			 confidence, state, opened_at, closed_at, close_reason,
			 created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
		ON CONFLICT (id) DO UPDATE SET
			trend_ids = EXCLUDED.trend_ids,
			trend_types = EXCLUDED.trend_types,
			confidence = EXCLUDED.confidence,
			state = EXCLUDED.state,
			closed_at = EXCLUDED.closed_at,
			close_reason = EXCLUDED.close_reason,
			updated_at = EXCLUDED.updated_at`,
		c.ID, c.MatchID, string(c.ClusterType), trendIDs, trendTypes,
		c.Confidence, st, openedAt, c.ClosedAt, c.CloseReason,
		c.CreatedAt, c.UpdatedAt,
	)
	if err != nil {
		return fmt.Errorf("clusters save: %w", err)
	}
	return nil
}

func (r *ClusterRepo) ListActiveByMatch(
	ctx context.Context, matchID string,
) ([]cluster.TrendCluster, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT `+clusterColumns+`
		FROM nexus.trend_clusters
		WHERE match_id = $1 AND state = 'ACTIVE'
		ORDER BY opened_at ASC`, matchID)
	if err != nil {
		return nil, fmt.Errorf("clusters list active: %w", err)
	}
	defer rows.Close()
	return scanClusters(rows, 64)
}

func (r *ClusterRepo) List(ctx context.Context, limit int) ([]cluster.TrendCluster, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT `+clusterColumns+`
		FROM nexus.trend_clusters
		ORDER BY updated_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, fmt.Errorf("clusters list: %w", err)
	}
	defer rows.Close()
	return scanClusters(rows, limit)
}

func scanClusters(rows pgx.Rows, limit int) ([]cluster.TrendCluster, error) {
	out := make([]cluster.TrendCluster, 0, limit)
	for rows.Next() {
		c, err := scanCluster(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func scanCluster(row rowScanner) (cluster.TrendCluster, error) {
	var (
		c           cluster.TrendCluster
		clusterType string
		st          string
		trendIDs    []byte
		trendTypes  []byte
	)
	err := row.Scan(&c.ID, &c.MatchID, &clusterType, &trendIDs, &trendTypes,
		&c.Confidence, &st, &c.OpenedAt, &c.ClosedAt, &c.CloseReason,
		&c.CreatedAt, &c.UpdatedAt)
	if err != nil {
		return cluster.TrendCluster{}, err
	}
	c.ClusterType = cluster.Type(clusterType)
	c.State = cluster.State(st)
	if err := json.Unmarshal(trendIDs, &c.TrendIDs); err != nil {
		return cluster.TrendCluster{}, fmt.Errorf("clusters: trend_ids: %w", err)
	}
	if err := json.Unmarshal(trendTypes, &c.TrendTypes); err != nil {
		return cluster.TrendCluster{}, fmt.Errorf("clusters: trend_types: %w", err)
	}
	return c, nil
}

// ---- DecisionRepo ----------------------------------------------------------------

type DecisionRepo struct{ pool *pgxpool.Pool }

func NewDecisionRepo(pool *pgxpool.Pool) *DecisionRepo { return &DecisionRepo{pool: pool} }

func (r *DecisionRepo) Record(ctx context.Context, d decision.PublicationDecision) error {
	reasoning, err := json.Marshal(d.Reasoning)
	if err != nil {
		return fmt.Errorf("decisions: marshal reasoning: %w", err)
	}
	_, err = r.pool.Exec(ctx, `
		INSERT INTO nexus.publication_decisions
			(id, agent_id, trend_id, cluster_id, match_id, action,
			 priority, reasoning, confidence, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
		d.ID, d.AgentID, d.TrendID, d.ClusterID, d.MatchID,
		string(d.Action), string(d.Priority), reasoning, d.Confidence, d.CreatedAt,
	)
	if err != nil {
		return fmt.Errorf("decisions record: %w", err)
	}
	return nil
}

func (r *DecisionRepo) List(ctx context.Context, limit int) ([]decision.PublicationDecision, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, agent_id, trend_id, cluster_id, match_id, action,
		       priority, reasoning, confidence, created_at
		FROM nexus.publication_decisions
		ORDER BY created_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, fmt.Errorf("decisions list: %w", err)
	}
	defer rows.Close()
	out := make([]decision.PublicationDecision, 0, limit)
	for rows.Next() {
		var (
			d         decision.PublicationDecision
			action    string
			priority  string
			reasoning []byte
		)
		if err := rows.Scan(&d.ID, &d.AgentID, &d.TrendID, &d.ClusterID,
			&d.MatchID, &action, &priority, &reasoning, &d.Confidence,
			&d.CreatedAt); err != nil {
			return nil, err
		}
		d.Action = decision.Action(action)
		d.Priority = decision.Priority(priority)
		if err := json.Unmarshal(reasoning, &d.Reasoning); err != nil {
			return nil, fmt.Errorf("decisions: reasoning: %w", err)
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

// ---- AgentStateRepo ----------------------------------------------------------------

type AgentStateRepo struct{ pool *pgxpool.Pool }

func NewAgentStateRepo(pool *pgxpool.Pool) *AgentStateRepo {
	return &AgentStateRepo{pool: pool}
}

func (r *AgentStateRepo) Get(
	ctx context.Context, agentID uuid.UUID, matchID string, clusterID uuid.UUID,
) (state.AgentState, error) {
	row := r.pool.QueryRow(ctx, `
		SELECT id, agent_id, match_id, cluster_id, cluster_type,
		       current_state, history, created_at, updated_at
		FROM nexus.agent_states
		WHERE agent_id = $1 AND match_id = $2 AND cluster_id = $3`,
		agentID, matchID, clusterID)
	s, err := scanState(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return state.AgentState{}, ports.ErrNotFound
	}
	return s, err
}

func (r *AgentStateRepo) Save(ctx context.Context, s state.AgentState) error {
	history, err := json.Marshal(s.History)
	if err != nil {
		return fmt.Errorf("states: marshal history: %w", err)
	}
	_, err = r.pool.Exec(ctx, `
		INSERT INTO nexus.agent_states
			(id, agent_id, match_id, cluster_id, cluster_type,
			 current_state, history, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
		ON CONFLICT (agent_id, match_id, cluster_id) DO UPDATE SET
			current_state = EXCLUDED.current_state,
			history = EXCLUDED.history,
			updated_at = EXCLUDED.updated_at`,
		s.ID, s.AgentID, s.MatchID, s.ClusterID, s.ClusterType,
		string(s.Current), history, s.CreatedAt, s.UpdatedAt,
	)
	if err != nil {
		return fmt.Errorf("states save: %w", err)
	}
	return nil
}

func (r *AgentStateRepo) ListActiveByMatch(
	ctx context.Context, matchID string,
) ([]state.AgentState, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, agent_id, match_id, cluster_id, cluster_type,
		       current_state, history, created_at, updated_at
		FROM nexus.agent_states
		WHERE match_id = $1
		  AND current_state IN ('OBSERVING','TRACKING','ALERTING')
		ORDER BY updated_at ASC`, matchID)
	if err != nil {
		return nil, fmt.Errorf("states list active: %w", err)
	}
	defer rows.Close()
	out := make([]state.AgentState, 0, 16)
	for rows.Next() {
		s, err := scanState(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func (r *AgentStateRepo) ListByAgent(
	ctx context.Context, agentID uuid.UUID, limit int,
) ([]state.AgentState, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, agent_id, match_id, cluster_id, cluster_type,
		       current_state, history, created_at, updated_at
		FROM nexus.agent_states
		WHERE agent_id = $1
		ORDER BY updated_at DESC LIMIT $2`, agentID, limit)
	if err != nil {
		return nil, fmt.Errorf("states list: %w", err)
	}
	defer rows.Close()
	out := make([]state.AgentState, 0, limit)
	for rows.Next() {
		s, err := scanState(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func scanState(row rowScanner) (state.AgentState, error) {
	var (
		s       state.AgentState
		current string
		history []byte
	)
	err := row.Scan(&s.ID, &s.AgentID, &s.MatchID, &s.ClusterID,
		&s.ClusterType, &current, &history, &s.CreatedAt, &s.UpdatedAt)
	if err != nil {
		return state.AgentState{}, err
	}
	s.Current = state.State(current)
	if err := json.Unmarshal(history, &s.History); err != nil {
		return state.AgentState{}, fmt.Errorf("states: history: %w", err)
	}
	return s, nil
}

// ---- EvolutionRepo ----------------------------------------------------------------

type EvolutionRepo struct{ pool *pgxpool.Pool }

func NewEvolutionRepo(pool *pgxpool.Pool) *EvolutionRepo {
	return &EvolutionRepo{pool: pool}
}

func (r *EvolutionRepo) Record(ctx context.Context, rec evolution.Record) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO nexus.draft_evolution
			(id, agent_id, cluster_id, draft_id, match_id, draft_type,
			 sequence, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
		rec.ID, rec.AgentID, rec.ClusterID, rec.DraftID, rec.MatchID,
		string(rec.DraftType), rec.Sequence, rec.CreatedAt,
	)
	if err != nil {
		return fmt.Errorf("evolution record: %w", err)
	}
	return nil
}

func (r *EvolutionRepo) CountForCluster(
	ctx context.Context, agentID uuid.UUID, clusterID uuid.UUID,
) (int, error) {
	var count int
	err := r.pool.QueryRow(ctx, `
		SELECT count(*) FROM nexus.draft_evolution
		WHERE agent_id = $1 AND cluster_id = $2`,
		agentID, clusterID).Scan(&count)
	if err != nil {
		return 0, fmt.Errorf("evolution count: %w", err)
	}
	return count, nil
}

func (r *EvolutionRepo) ListByCluster(
	ctx context.Context, clusterID uuid.UUID, limit int,
) ([]evolution.Record, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, agent_id, cluster_id, draft_id, match_id, draft_type,
		       sequence, created_at
		FROM nexus.draft_evolution
		WHERE cluster_id = $1
		ORDER BY created_at ASC LIMIT $2`, clusterID, limit)
	if err != nil {
		return nil, fmt.Errorf("evolution list by cluster: %w", err)
	}
	defer rows.Close()
	return scanEvolution(rows, limit)
}

func (r *EvolutionRepo) List(ctx context.Context, limit int) ([]evolution.Record, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT id, agent_id, cluster_id, draft_id, match_id, draft_type,
		       sequence, created_at
		FROM nexus.draft_evolution
		ORDER BY created_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, fmt.Errorf("evolution list: %w", err)
	}
	defer rows.Close()
	return scanEvolution(rows, limit)
}

func scanEvolution(rows pgx.Rows, limit int) ([]evolution.Record, error) {
	out := make([]evolution.Record, 0, limit)
	for rows.Next() {
		var (
			rec       evolution.Record
			draftType string
		)
		if err := rows.Scan(&rec.ID, &rec.AgentID, &rec.ClusterID,
			&rec.DraftID, &rec.MatchID, &draftType, &rec.Sequence,
			&rec.CreatedAt); err != nil {
			return nil, err
		}
		rec.DraftType = evolution.DraftType(draftType)
		out = append(out, rec)
	}
	return out, rows.Err()
}

var (
	_ ports.ClusterRepository    = (*ClusterRepo)(nil)
	_ ports.DecisionRepository   = (*DecisionRepo)(nil)
	_ ports.AgentStateRepository = (*AgentStateRepo)(nil)
	_ ports.EvolutionRepository  = (*EvolutionRepo)(nil)
)
