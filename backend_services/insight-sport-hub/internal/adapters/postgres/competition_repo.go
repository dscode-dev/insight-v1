// Postgres CompetitionRegistry — Sprint 2 replacement for the
// in-memory adapter.
//
// Adapters never store provider-native ids in domain types. They
// call LookupByExternalID at ingestion time + persist a row in
// competition_external_ids on first encounter (Sprint 3+ will add
// background sync; Sprint 2 calls LinkExternalID lazily from each
// adapter's FetchFixtures/FetchStandings path).
package postgres

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

type CompetitionRepo struct {
	pool Pool
}

func NewCompetitionRepo(p Pool) *CompetitionRepo { return &CompetitionRepo{pool: p} }

const compCols = `id, slug, name, country_code, enabled`

func (r *CompetitionRepo) IsKnown(ctx context.Context, id uuid.UUID) (bool, error) {
	var enabled bool
	err := r.pool.QueryRow(ctx,
		`SELECT enabled FROM competitions WHERE id = $1`, id,
	).Scan(&enabled)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return false, nil
		}
		return false, fmt.Errorf("competition IsKnown: %w", err)
	}
	return enabled, nil
}

func (r *CompetitionRepo) Register(ctx context.Context, c ports.Competition) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO competitions (id, slug, name, country_code, enabled)
		VALUES ($1, $2, $3, $4, $5)
	`, c.ID, c.Slug, c.Name, c.CountryCode, c.Enabled)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.UniqueViolation {
			return ports.ErrDuplicate
		}
		return fmt.Errorf("competition register: %w", err)
	}
	return nil
}

func (r *CompetitionRepo) Lookup(ctx context.Context, id uuid.UUID) (ports.Competition, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+compCols+` FROM competitions WHERE id = $1`, id)
	return scanCompetition(row)
}

func (r *CompetitionRepo) LookupByExternalID(
	ctx context.Context, sourceID, externalID string,
) (ports.Competition, error) {
	row := r.pool.QueryRow(ctx, `
		SELECT `+aliasedCompCols+`
		  FROM competitions c
		  JOIN competition_external_ids ex
		    ON ex.competition_id = c.id
		 WHERE ex.source_id = $1 AND ex.external_id = $2
	`, sourceID, externalID)
	return scanCompetition(row)
}

func (r *CompetitionRepo) GetExternalIDForSource(
	ctx context.Context, competitionID uuid.UUID, sourceID string,
) (string, error) {
	var externalID string
	err := r.pool.QueryRow(ctx, `
		SELECT external_id
		  FROM competition_external_ids
		 WHERE competition_id = $1 AND source_id = $2
	`, competitionID, sourceID).Scan(&externalID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return "", ports.ErrNotFound
		}
		return "", fmt.Errorf("competition get external id: %w", err)
	}
	return externalID, nil
}

func (r *CompetitionRepo) LinkExternalID(
	ctx context.Context, competitionID uuid.UUID, sourceID, externalID string,
) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO competition_external_ids (competition_id, source_id, external_id)
		VALUES ($1, $2, $3)
		ON CONFLICT (source_id, external_id) DO NOTHING
	`, competitionID, sourceID, externalID)
	if err != nil {
		return fmt.Errorf("competition link external: %w", err)
	}
	return nil
}

func (r *CompetitionRepo) SetEnabled(
	ctx context.Context, id uuid.UUID, enabled bool,
) error {
	cmd, err := r.pool.Exec(ctx, `
		UPDATE competitions
		   SET enabled = $2, updated_at = NOW()
		 WHERE id = $1
	`, id, enabled)
	if err != nil {
		return fmt.Errorf("competition set enabled: %w", err)
	}
	if cmd.RowsAffected() == 0 {
		return ports.ErrNotFound
	}
	return nil
}

func (r *CompetitionRepo) List(ctx context.Context) ([]ports.Competition, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT `+compCols+` FROM competitions ORDER BY country_code, name`)
	if err != nil {
		return nil, fmt.Errorf("competition list: %w", err)
	}
	defer rows.Close()
	out := make([]ports.Competition, 0)
	for rows.Next() {
		c, err := scanCompetition(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

const aliasedCompCols = `c.id, c.slug, c.name, c.country_code, c.enabled`

func scanCompetition(r rowScanner) (ports.Competition, error) {
	var c ports.Competition
	err := r.Scan(&c.ID, &c.Slug, &c.Name, &c.CountryCode, &c.Enabled)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return ports.Competition{}, ports.ErrNotFound
		}
		return ports.Competition{}, fmt.Errorf("competition scan: %w", err)
	}
	return c, nil
}
