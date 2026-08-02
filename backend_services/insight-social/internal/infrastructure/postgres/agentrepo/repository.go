// Package agentrepo is the pgx-backed AgentProfile repository.
// Profiles are migration-seeded; this repo only reads.
package agentrepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	domagent "github.com/konoha-labs/insight-social/internal/domain/agent"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

const selectCols = `id, slug, name, avatar, bio, active, verified, created_at`

func (r *Repository) List(ctx context.Context, activeOnly bool) ([]*domagent.Profile, error) {
	query := `SELECT ` + selectCols + ` FROM agent_profiles`
	if activeOnly {
		query += ` WHERE active = TRUE`
	}
	query += ` ORDER BY slug`
	rows, err := r.pool.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("agentrepo list: %w", err)
	}
	defer rows.Close()
	var out []*domagent.Profile
	for rows.Next() {
		p, err := scan(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

func (r *Repository) GetByID(ctx context.Context, id uuid.UUID) (*domagent.Profile, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+selectCols+` FROM agent_profiles WHERE id = $1`, id)
	return scanOne(row)
}

func (r *Repository) GetBySlug(ctx context.Context, slug string) (*domagent.Profile, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+selectCols+` FROM agent_profiles WHERE slug = $1`, slug)
	return scanOne(row)
}

// IsActive reports whether an agent may currently publish. Missing agent ⇒
// ErrNotFound (fail-closed: the publication path rejects unknown authors).
func (r *Repository) IsActive(ctx context.Context, id uuid.UUID) (bool, error) {
	var active bool
	err := r.pool.QueryRow(ctx, `SELECT active FROM agent_profiles WHERE id = $1`, id).Scan(&active)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return false, domagent.ErrNotFound
		}
		return false, fmt.Errorf("agentrepo isactive: %w", err)
	}
	return active, nil
}

// AgentStateEvent is one durable operational transition (deactivate/reactivate).
type AgentStateEvent struct {
	Action        string
	Reason        string
	OperatorID    string
	CorrelationID string
	CreatedAt     string
}

// SetActive transitions an agent's operational state and, on a real change,
// records a durable operator-attributed history row (single transaction). It is
// idempotent: setting the current state is a no-op that returns the state without
// a spurious history row. Missing agent ⇒ ErrNotFound.
func (r *Repository) SetActive(ctx context.Context, id uuid.UUID, active bool, reason, operatorID, correlationID string) (bool, error) {
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return false, fmt.Errorf("agentrepo setactive begin: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var current bool
	if err := tx.QueryRow(ctx, `SELECT active FROM agent_profiles WHERE id = $1 FOR UPDATE`, id).Scan(&current); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return false, domagent.ErrNotFound
		}
		return false, fmt.Errorf("agentrepo setactive lock: %w", err)
	}
	if current == active {
		return current, nil // idempotent no-op
	}

	action := "reactivate"
	if !active {
		action = "deactivate"
	}
	if active {
		_, err = tx.Exec(ctx, `UPDATE agent_profiles SET active = TRUE, deactivated_at = NULL, deactivated_reason = NULL WHERE id = $1`, id)
	} else {
		_, err = tx.Exec(ctx, `UPDATE agent_profiles SET active = FALSE, deactivated_at = NOW(), deactivated_reason = $2 WHERE id = $1`, id, reason)
	}
	if err != nil {
		return false, fmt.Errorf("agentrepo setactive update: %w", err)
	}
	var corr any
	if correlationID != "" {
		corr = correlationID
	}
	if _, err := tx.Exec(ctx,
		`INSERT INTO agent_state_events (agent_id, action, reason, operator_id, correlation_id) VALUES ($1, $2, $3, $4, $5)`,
		id, action, reason, operatorID, corr); err != nil {
		return false, fmt.Errorf("agentrepo setactive event: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return false, fmt.Errorf("agentrepo setactive commit: %w", err)
	}
	return active, nil
}

// StateEvents returns the agent's operational history, newest first (read model).
func (r *Repository) StateEvents(ctx context.Context, id uuid.UUID, limit int) ([]AgentStateEvent, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	rows, err := r.pool.Query(ctx, `
SELECT action, reason, operator_id, COALESCE(correlation_id, ''), created_at
  FROM agent_state_events WHERE agent_id = $1 ORDER BY created_at DESC, id DESC LIMIT $2`, id, limit)
	if err != nil {
		return nil, fmt.Errorf("agentrepo stateevents: %w", err)
	}
	defer rows.Close()
	out := []AgentStateEvent{}
	for rows.Next() {
		var e AgentStateEvent
		var ts time.Time
		if err := rows.Scan(&e.Action, &e.Reason, &e.OperatorID, &e.CorrelationID, &ts); err != nil {
			return nil, err
		}
		e.CreatedAt = ts.UTC().Format(time.RFC3339)
		out = append(out, e)
	}
	return out, rows.Err()
}

type scannable interface{ Scan(dest ...any) error }

func scan(row scannable) (*domagent.Profile, error) {
	p := &domagent.Profile{}
	err := row.Scan(&p.ID, &p.Slug, &p.Name, &p.Avatar, &p.Bio,
		&p.Active, &p.Verified, &p.CreatedAt)
	if err != nil {
		return nil, fmt.Errorf("agentrepo scan: %w", err)
	}
	p.CreatedAt = p.CreatedAt.UTC()
	return p, nil
}

func scanOne(row scannable) (*domagent.Profile, error) {
	p, err := scan(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) ||
			errors.Is(errors.Unwrap(err), pgx.ErrNoRows) {
			return nil, domagent.ErrNotFound
		}
		return nil, err
	}
	return p, nil
}
