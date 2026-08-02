// PostgresDeadLetterStore — Sprint 5.1.
//
// Persists terminal SyncJob failures in the `dead_letter_failures`
// table (migration 00003). Satisfies both ports.DeadLetterStore
// (Record only — the queue adapter's view) and ports.DeadLetterReader
// (List / Get / MarkReplayed — the HTTP handler's view).
//
// Architectural rule: this is the ONLY persistent surface for
// failures. Sprint 4 shipped NoopDLQ; the application code path is
// unchanged when this adapter is wired instead.
package postgres

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

type DeadLetterRepo struct {
	pool Pool
}

func NewDeadLetterRepo(p Pool) *DeadLetterRepo { return &DeadLetterRepo{pool: p} }

const dlqInsertSQL = `
INSERT INTO dead_letter_failures
    (job_id, provider_id, competition_id, sync_type,
     reason, failure_type, attempts, failed_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
`

// Record — ports.DeadLetterStore. Classifies the supplied reason at
// write time so the persisted row carries the band (Transient,
// Provider, Infrastructure, Validation, Permanent). This makes the
// failure_type column queryable without re-running the classifier.
//
// Errors here are logged by the queue adapter but never bubble up
// past the consumer loop — DLQ persistence failures must not stop
// the worker.
func (r *DeadLetterRepo) Record(ctx context.Context, f syncdom.SyncJobFailure) error {
	ft := syncdom.ClassifyReason(f.Reason)
	_, err := r.pool.Exec(ctx, dlqInsertSQL,
		f.JobID.String(),
		f.ProviderID,
		f.CompetitionID,
		string(f.SyncType),
		f.Reason,
		string(ft),
		f.Attempts,
		f.FailedAt,
	)
	if err != nil {
		return fmt.Errorf("dlq record: %w", err)
	}
	return nil
}

const dlqSelectCols = `id, job_id, provider_id, competition_id, sync_type,
    reason, failure_type, attempts, failed_at, replayed_at, created_at`

// List — ports.DeadLetterReader. Cursor-less for Sprint 5.1; admin
// volumes are small enough that Limit/Offset suffices. Sprint 6+
// may upgrade to a keyset cursor on (failed_at, id).
func (r *DeadLetterRepo) List(ctx context.Context, q ports.DeadLetterQuery) ([]ports.DeadLetterRecord, error) {
	limit := q.Limit
	if limit <= 0 {
		limit = 50
	}
	if limit > 500 {
		limit = 500
	}
	// Build the WHERE clause dynamically — small set, OK to do
	// without a query builder.
	clauses := []string{"1=1"}
	args := []any{}
	if q.Provider != "" {
		args = append(args, q.Provider)
		clauses = append(clauses, fmt.Sprintf("provider_id = $%d", len(args)))
	}
	if q.FailureType != "" {
		args = append(args, q.FailureType)
		clauses = append(clauses, fmt.Sprintf("failure_type = $%d", len(args)))
	}
	if q.Unreplayed {
		clauses = append(clauses, "replayed_at IS NULL")
	}
	args = append(args, limit)
	limitPlace := fmt.Sprintf("$%d", len(args))
	args = append(args, q.Offset)
	offsetPlace := fmt.Sprintf("$%d", len(args))
	sql := fmt.Sprintf(
		`SELECT %s FROM dead_letter_failures
WHERE %s
ORDER BY failed_at DESC
LIMIT %s OFFSET %s`,
		dlqSelectCols, joinSep(clauses, " AND "), limitPlace, offsetPlace,
	)
	rows, err := r.pool.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("dlq list: %w", err)
	}
	defer rows.Close()
	out := make([]ports.DeadLetterRecord, 0, limit)
	for rows.Next() {
		rec, err := scanDLQRow(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, rec)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("dlq list rows: %w", err)
	}
	return out, nil
}

// Get — single failure by id. Returns ports.ErrNotFound when absent.
func (r *DeadLetterRepo) Get(ctx context.Context, id string) (ports.DeadLetterRecord, error) {
	sql := `SELECT ` + dlqSelectCols + ` FROM dead_letter_failures WHERE id = $1`
	rows, err := r.pool.Query(ctx, sql, id)
	if err != nil {
		return ports.DeadLetterRecord{}, fmt.Errorf("dlq get: %w", err)
	}
	defer rows.Close()
	if !rows.Next() {
		return ports.DeadLetterRecord{}, ports.ErrNotFound
	}
	return scanDLQRow(rows)
}

// MarkReplayed sets replayed_at. Idempotent — repeated calls
// overwrite the timestamp. Sprint 6 may keep an audit table of
// replays; today we just stamp the latest.
func (r *DeadLetterRepo) MarkReplayed(ctx context.Context, id string, at time.Time) error {
	cmd, err := r.pool.Exec(ctx,
		`UPDATE dead_letter_failures SET replayed_at = $2 WHERE id = $1`,
		id, at.UTC(),
	)
	if err != nil {
		return fmt.Errorf("dlq mark replayed: %w", err)
	}
	if cmd.RowsAffected() == 0 {
		return ports.ErrNotFound
	}
	return nil
}

// scanDLQRow — shared scanner for List + Get. Keeps the column
// order in lock step with dlqSelectCols.
func scanDLQRow(rows pgx.Rows) (ports.DeadLetterRecord, error) {
	var (
		id          string
		jobID       string
		providerID  string
		competition [16]byte
		syncType    string
		reason      string
		failureType string
		attempts    int
		failedAt    time.Time
		replayedAt  *time.Time
		createdAt   time.Time
	)
	// pgx scans uuid columns into [16]byte via the UUIDOID codec; we
	// then convert to a string for the read model.
	if err := rows.Scan(
		&id, &jobID, &providerID, &competition, &syncType,
		&reason, &failureType, &attempts, &failedAt, &replayedAt, &createdAt,
	); err != nil {
		return ports.DeadLetterRecord{}, fmt.Errorf("dlq scan: %w", err)
	}
	jobUUID, err := syncdom.ParseJobID(jobID)
	if err != nil {
		return ports.DeadLetterRecord{}, fmt.Errorf("dlq scan job_id: %w", err)
	}
	compUUID, err := uuidFromBytes(competition)
	if err != nil {
		return ports.DeadLetterRecord{}, err
	}
	rec := ports.DeadLetterRecord{
		ID: id,
		Failure: syncdom.SyncJobFailure{
			JobID:         jobUUID,
			ProviderID:    providerID,
			CompetitionID: compUUID,
			SyncType:      syncdom.SyncType(syncType),
			Reason:        reason,
			Attempts:      attempts,
			FailedAt:      failedAt,
		},
		ReplayedAt: replayedAt,
		CreatedAt:  createdAt,
	}
	// failure_type is informational on the read model — derive on
	// re-classification for callers that need it without trusting
	// historical writes.
	_ = failureType
	return rec, nil
}

// joinSep — tiny helper because importing "strings" for a single
// Join would add an import line for no real benefit.
func joinSep(parts []string, sep string) string {
	if len(parts) == 0 {
		return ""
	}
	out := parts[0]
	for _, p := range parts[1:] {
		out += sep + p
	}
	return out
}

// Compile-time guard — both interfaces must remain satisfied as
// the port shape evolves.
var (
	_ ports.DeadLetterStore  = (*DeadLetterRepo)(nil)
	_ ports.DeadLetterReader = (*DeadLetterRepo)(nil)
)

// errInvalidUUID — surfaced when pgx hands us bytes the uuid pkg
// can't parse. Almost always a schema/codec drift, never user input.
var errInvalidUUID = errors.New("postgres dlq: invalid uuid bytes")

// uuidFromBytes — pgx scans UUID columns into [16]byte. Convert to
// the google/uuid type via FromBytes which validates length.
func uuidFromBytes(b [16]byte) (uuid.UUID, error) {
	u, err := uuid.FromBytes(b[:])
	if err != nil {
		return uuid.UUID{}, fmt.Errorf("%w: %s", errInvalidUUID, err.Error())
	}
	return u, nil
}
