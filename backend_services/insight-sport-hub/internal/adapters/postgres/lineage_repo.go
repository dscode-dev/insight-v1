package postgres

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/lineage"
)

type LineageRepo struct {
	pool Pool
}

func NewLineageRepo(p Pool) *LineageRepo { return &LineageRepo{pool: p} }

// Link is idempotent — the UNIQUE (canonical_event_id, raw_event_id)
// constraint catches re-runs of the same lineage row + we swallow
// the duplicate violation so the orchestrator's flow remains
// idempotent without conditional inserts.
const linkSQL = `
INSERT INTO event_lineage (canonical_event_id, raw_event_id)
VALUES ($1, $2)
ON CONFLICT DO NOTHING
`

func (r *LineageRepo) Link(ctx context.Context, canonicalID, rawID uuid.UUID) error {
	_, err := r.pool.Exec(ctx, linkSQL, canonicalID, rawID)
	if err != nil {
		// Foreign-key violations bubble up — they indicate the caller
		// tried to link a raw or canonical that doesn't exist, which
		// is an orchestrator bug not an operational failure.
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.ForeignKeyViolation {
			return fmt.Errorf("lineage link FK violation: %w", err)
		}
		return fmt.Errorf("lineage link: %w", err)
	}
	return nil
}

// GraphFor pulls the canonical's lineage projection. Empty result on
// unknown canonical (no error) — caller decides whether absence is
// noteworthy.
const graphSQL = `
SELECT r.raw_event_id, r.source_id, r.source_type,
       r.external_match_id, r.event_type, r.observed_at,
       r.raw_confidence, l.created_at
  FROM event_lineage l
  JOIN raw_sports_events r ON r.raw_event_id = l.raw_event_id
 WHERE l.canonical_event_id = $1
 ORDER BY r.observed_at ASC
`

func (r *LineageRepo) GraphFor(
	ctx context.Context, canonicalID uuid.UUID,
) (lineage.Graph, error) {
	rows, err := r.pool.Query(ctx, graphSQL, canonicalID)
	if err != nil {
		return lineage.Graph{}, fmt.Errorf("lineage graph: %w", err)
	}
	defer rows.Close()
	g := lineage.Graph{CanonicalEventID: canonicalID}
	for rows.Next() {
		var (
			rawID      uuid.UUID
			sourceID   string
			sourceType string
			externalID string
			eventType  string
			observedAt time.Time
			rawConf    float64
			linkedAt   time.Time
		)
		if err := rows.Scan(
			&rawID, &sourceID, &sourceType, &externalID,
			&eventType, &observedAt, &rawConf, &linkedAt,
		); err != nil {
			return lineage.Graph{}, fmt.Errorf("lineage graph scan: %w", err)
		}
		g.Raws = append(g.Raws, lineage.RawSnapshot{
			RawEventID:      rawID,
			SourceID:        sourceID,
			SourceType:      sourceType,
			ExternalMatchID: externalID,
			EventType:       eventType,
			ObservedAt:      observedAt.UTC(),
			RawConfidence:   rawConf,
			LinkedAt:        linkedAt.UTC(),
		})
	}
	return g, rows.Err()
}

const linksByRawSQL = `
SELECT canonical_event_id, raw_event_id, created_at
  FROM event_lineage
 WHERE raw_event_id = $1
 ORDER BY created_at ASC
`

func (r *LineageRepo) LinksFor(
	ctx context.Context, rawID uuid.UUID,
) ([]lineage.Link, error) {
	rows, err := r.pool.Query(ctx, linksByRawSQL, rawID)
	if err != nil {
		return nil, fmt.Errorf("lineage links: %w", err)
	}
	defer rows.Close()
	out := make([]lineage.Link, 0)
	for rows.Next() {
		var (
			canonicalID uuid.UUID
			rid         uuid.UUID
			linkedAt    time.Time
		)
		if err := rows.Scan(&canonicalID, &rid, &linkedAt); err != nil {
			return nil, fmt.Errorf("lineage links scan: %w", err)
		}
		out = append(out, lineage.Link{
			CanonicalEventID: canonicalID,
			RawEventID:       rid,
			LinkedAt:         linkedAt.UTC(),
		})
	}
	return out, rows.Err()
}
