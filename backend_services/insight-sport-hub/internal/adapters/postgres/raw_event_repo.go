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

type RawEventRepo struct {
	pool Pool
}

func NewRawEventRepo(p Pool) *RawEventRepo { return &RawEventRepo{pool: p} }

// The source JSONB column stores the FULL SourceRef — lineage rule.
// The payload JSONB column stores the raw payload verbatim.
// source_id/source_type are convenience extracts for indexed queries
// (e.g. "every raw from source X in window Y"). They MUST agree with
// the JSONB blob — the insert path always writes both from the same
// SourceRef so drift isn't possible without manual SQL.
const rawCols = `
raw_event_id, source, source_id, source_type,
sport, competition_id, external_match_id, event_type,
observed_at, payload, raw_confidence
`

const rawInsertSQL = `
INSERT INTO raw_sports_events (
    raw_event_id, source, source_id, source_type,
    sport, competition_id, external_match_id, event_type,
    observed_at, payload, raw_confidence
) VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
`

func (r *RawEventRepo) Insert(ctx context.Context, raw *event.RawSportsEvent) error {
	sourceJSON, err := json.Marshal(raw.Source())
	if err != nil {
		return fmt.Errorf("raw insert: marshal source: %w", err)
	}
	payloadJSON, err := json.Marshal(raw.Payload())
	if err != nil {
		return fmt.Errorf("raw insert: marshal payload: %w", err)
	}

	_, err = r.pool.Exec(ctx, rawInsertSQL,
		raw.RawEventID(),
		string(sourceJSON),
		raw.Source().SourceID,
		string(raw.Source().Type),
		string(raw.Sport()),
		raw.CompetitionID(),
		raw.ExternalMatchID(),
		raw.EventType(),
		raw.ObservedAt(),
		string(payloadJSON),
		raw.RawConfidence(),
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.UniqueViolation {
			return ports.ErrDuplicate
		}
		return fmt.Errorf("raw insert: %w", err)
	}
	return nil
}

func (r *RawEventRepo) GetByID(ctx context.Context, id uuid.UUID) (*event.RawSportsEvent, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+rawCols+` FROM raw_sports_events WHERE raw_event_id = $1`, id)
	return scanRawEvent(row)
}

// ListForIdentity returns every raw whose derived match_id matches
// the supplied Identity. Sprint 1 implementation: query on the
// (sport, competition, event_type) tuple + filter client-side on
// the derived match_id (UUIDv5 over source_id + external_match_id).
//
// This is a known Sprint 1 placeholder — Sprint 2's match catalogue
// will replace the client-side filter with a direct match_id query
// once external_match_id → match_id mapping is stored.
func (r *RawEventRepo) ListForIdentity(
	ctx context.Context,
	id event.Identity,
) ([]*event.RawSportsEvent, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT `+rawCols+`
		  FROM raw_sports_events
		 WHERE sport = $1 AND competition_id = $2 AND event_type = $3
		 ORDER BY observed_at ASC
	`,
		string(id.Sport), id.CompetitionID, id.EventType,
	)
	if err != nil {
		return nil, fmt.Errorf("raw list identity: %w", err)
	}
	defer rows.Close()

	matchNS := uuid.MustParse("8e2e3f9c-3d23-4ad1-9c1e-2b91a1f9c6f0")
	out := make([]*event.RawSportsEvent, 0)
	for rows.Next() {
		row, err := scanRawEvent(rows)
		if err != nil {
			return nil, err
		}
		derived := uuid.NewSHA1(matchNS,
			[]byte(row.Source().SourceID+"::"+row.ExternalMatchID()))
		if derived == id.MatchID {
			out = append(out, row)
		}
	}
	return out, rows.Err()
}

func (r *RawEventRepo) ExistsByID(ctx context.Context, id uuid.UUID) (bool, error) {
	var exists bool
	err := r.pool.QueryRow(ctx,
		`SELECT EXISTS(SELECT 1 FROM raw_sports_events WHERE raw_event_id = $1)`, id,
	).Scan(&exists)
	if err != nil {
		return false, fmt.Errorf("raw exists: %w", err)
	}
	return exists, nil
}

func scanRawEvent(r rowScanner) (*event.RawSportsEvent, error) {
	var (
		id            uuid.UUID
		sourceJSON    []byte
		sourceID      string
		sourceType    string
		sportStr      string
		competitionID uuid.UUID
		externalID    string
		eventType     string
		observedAt    time.Time
		payloadJSON   []byte
		rawConfidence float64
	)
	err := r.Scan(
		&id, &sourceJSON, &sourceID, &sourceType,
		&sportStr, &competitionID, &externalID, &eventType,
		&observedAt, &payloadJSON, &rawConfidence,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ports.ErrNotFound
		}
		return nil, fmt.Errorf("raw scan: %w", err)
	}
	var ref source.SourceRef
	if err := json.Unmarshal(sourceJSON, &ref); err != nil {
		return nil, fmt.Errorf("raw scan: unmarshal source: %w", err)
	}
	var payload map[string]any
	if err := json.Unmarshal(payloadJSON, &payload); err != nil {
		return nil, fmt.Errorf("raw scan: unmarshal payload: %w", err)
	}
	return event.ReconstituteRaw(
		id, ref, sport.Sport(sportStr), competitionID,
		externalID, eventType, observedAt.UTC(),
		payload, rawConfidence,
	), nil
}
