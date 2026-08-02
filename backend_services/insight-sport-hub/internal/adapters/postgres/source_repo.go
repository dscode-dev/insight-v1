package postgres

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	domsource "github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

type SourceRepo struct {
	pool Pool
}

func NewSourceRepo(p Pool) *SourceRepo { return &SourceRepo{pool: p} }

const sourceCols = `id, name, type, priority, enabled, confidence_weight`

const sourceInsertSQL = `
INSERT INTO sources (id, name, type, priority, enabled, confidence_weight)
VALUES ($1, $2, $3, $4, $5, $6)
`

func (r *SourceRepo) Insert(ctx context.Context, s *domsource.Source) error {
	_, err := r.pool.Exec(ctx, sourceInsertSQL,
		s.ID(), s.Name(), string(s.Type()), s.Priority(), s.Enabled(), s.ConfidenceWeight(),
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.UniqueViolation {
			return ports.ErrDuplicate
		}
		return fmt.Errorf("source insert: %w", err)
	}
	return nil
}

func (r *SourceRepo) GetByID(ctx context.Context, id uuid.UUID) (*domsource.Source, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+sourceCols+` FROM sources WHERE id = $1`, id)
	return scanSource(row)
}

func (r *SourceRepo) GetByName(ctx context.Context, name string) (*domsource.Source, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+sourceCols+` FROM sources WHERE name = $1`, name)
	return scanSource(row)
}

func (r *SourceRepo) List(ctx context.Context) ([]*domsource.Source, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT `+sourceCols+` FROM sources ORDER BY priority ASC, name ASC`)
	if err != nil {
		return nil, fmt.Errorf("source list: %w", err)
	}
	defer rows.Close()
	out := make([]*domsource.Source, 0)
	for rows.Next() {
		s, err := scanSource(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

const sourceUpdateSQL = `
UPDATE sources
   SET name = $2, type = $3, priority = $4,
       enabled = $5, confidence_weight = $6,
       updated_at = NOW()
 WHERE id = $1
`

func (r *SourceRepo) Update(ctx context.Context, s *domsource.Source) error {
	cmd, err := r.pool.Exec(ctx, sourceUpdateSQL,
		s.ID(), s.Name(), string(s.Type()), s.Priority(), s.Enabled(), s.ConfidenceWeight(),
	)
	if err != nil {
		return fmt.Errorf("source update: %w", err)
	}
	if cmd.RowsAffected() == 0 {
		return ports.ErrNotFound
	}
	return nil
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanSource(r rowScanner) (*domsource.Source, error) {
	var (
		id       uuid.UUID
		name     string
		typeStr  string
		priority int
		enabled  bool
		weight   float64
	)
	err := r.Scan(&id, &name, &typeStr, &priority, &enabled, &weight)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ports.ErrNotFound
		}
		return nil, fmt.Errorf("source scan: %w", err)
	}
	return domsource.Reconstitute(
		id, name, domsource.SourceType(typeStr), priority, enabled, weight,
	), nil
}
