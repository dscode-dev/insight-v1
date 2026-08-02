package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

type CanonicalEventRepo struct {
	pool Pool
}

func NewCanonicalEventRepo(p Pool) *CanonicalEventRepo {
	return &CanonicalEventRepo{pool: p}
}

const canonicalCols = `
event_id, sport, competition_id, season, match_id, event_type,
status, confidence, sources, occurred_at, payload
`

// Upsert: INSERT … ON CONFLICT (identity 4-tuple) DO UPDATE.
// The natural identity (sport, competition_id, match_id, event_type)
// is UNIQUE — collision means "we already have this canonical;
// update its sources/payload/status/confidence in place".
const canonicalUpsertSQL = `
INSERT INTO canonical_sports_events (
    event_id, sport, competition_id, season, match_id, event_type,
    status, confidence, sources, occurred_at, payload
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11::jsonb)
ON CONFLICT (sport, competition_id, match_id, event_type) DO UPDATE
   SET status      = EXCLUDED.status,
       confidence  = EXCLUDED.confidence,
       sources     = EXCLUDED.sources,
       payload     = EXCLUDED.payload,
       occurred_at = EXCLUDED.occurred_at,
       updated_at  = NOW()
`

func (r *CanonicalEventRepo) Upsert(ctx context.Context, c *event.CanonicalSportsEvent) error {
	sourcesJSON, err := json.Marshal(c.Sources())
	if err != nil {
		return fmt.Errorf("canonical upsert: marshal sources: %w", err)
	}
	payloadJSON, err := json.Marshal(c.Payload())
	if err != nil {
		return fmt.Errorf("canonical upsert: marshal payload: %w", err)
	}

	var season any
	if c.Season() != "" {
		season = c.Season()
	}

	_, err = r.pool.Exec(ctx, canonicalUpsertSQL,
		c.EventID(),
		string(c.Sport()),
		c.CompetitionID(),
		season,
		c.MatchID(),
		c.EventType(),
		string(c.Status()),
		c.Confidence(),
		string(sourcesJSON),
		c.OccurredAt(),
		string(payloadJSON),
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.UniqueViolation {
			// Should be impossible with ON CONFLICT DO UPDATE — kept
			// as a safety net for the day the constraint shape
			// changes.
			return ports.ErrDuplicate
		}
		return fmt.Errorf("canonical upsert: %w", err)
	}
	return nil
}

func (r *CanonicalEventRepo) GetByID(
	ctx context.Context, id uuid.UUID,
) (*event.CanonicalSportsEvent, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+canonicalCols+` FROM canonical_sports_events WHERE event_id = $1`, id)
	return scanCanonical(row)
}

func (r *CanonicalEventRepo) GetByIdentity(
	ctx context.Context, id event.Identity,
) (*event.CanonicalSportsEvent, error) {
	row := r.pool.QueryRow(ctx, `
		SELECT `+canonicalCols+`
		  FROM canonical_sports_events
		 WHERE sport = $1 AND competition_id = $2
		   AND match_id = $3 AND event_type = $4
	`,
		string(id.Sport), id.CompetitionID, id.MatchID, id.EventType,
	)
	return scanCanonical(row)
}

func scanCanonical(r rowScanner) (*event.CanonicalSportsEvent, error) {
	var (
		eventID       uuid.UUID
		sportStr      string
		competitionID uuid.UUID
		season        *string
		matchID       uuid.UUID
		eventType     string
		statusStr     string
		confidence    float64
		sourcesJSON   []byte
		occurredAt    time.Time
		payloadJSON   []byte
	)
	err := r.Scan(
		&eventID, &sportStr, &competitionID, &season, &matchID, &eventType,
		&statusStr, &confidence, &sourcesJSON, &occurredAt, &payloadJSON,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ports.ErrNotFound
		}
		return nil, fmt.Errorf("canonical scan: %w", err)
	}

	var sources []source.SourceRef
	if err := json.Unmarshal(sourcesJSON, &sources); err != nil {
		return nil, fmt.Errorf("canonical scan: unmarshal sources: %w", err)
	}
	var payload map[string]any
	if err := json.Unmarshal(payloadJSON, &payload); err != nil {
		return nil, fmt.Errorf("canonical scan: unmarshal payload: %w", err)
	}

	seasonStr := ""
	if season != nil {
		seasonStr = *season
	}

	return event.ReconstituteCanonical(
		eventID,
		event.Identity{
			Sport:         sport.Sport(sportStr),
			CompetitionID: competitionID,
			MatchID:       matchID,
			EventType:     eventType,
		},
		seasonStr,
		event.Status(statusStr),
		confidence,
		sources,
		occurredAt.UTC(),
		payload,
	), nil
}
