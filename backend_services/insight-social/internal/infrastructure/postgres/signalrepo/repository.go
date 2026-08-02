// Package signalrepo is the pgx-backed Signal repository.
//
// Schema mapping (signals table — see migrations/00001_init.sql):
//
//	proto.label      ⇄ schema.kind          (varchar 32)
//	proto.body       ⇄ schema.body          (text, nullable)
//	proto.source     ⇄ schema.source        (varchar, lowercased)
//	proto.confidence ⇄ schema.confidence    (numeric → float64)
//	proto.ts         ⇄ schema.created_at    (timestamptz)
//
// Columns left at default: direction='neutral', value=0,
// weight_multiplier=1.0, minute=NULL. These are populated by the
// downstream scoring pipeline (Atlas), not by the
// Create RPC.
//
// State derivation:
//
//	The proto exposes SignalState (PENDING/VALIDATED/FLAGGED/...).
//	reputation_events.related_entity_id is typed UUID, so it cannot
//	reference a BIGSERIAL signal id without a schema change. Until
//	that linkage is added, every signal returns StatePending.
//	TODO(W2.2 follow-up): introduce signal_outcome table or migrate
//	signals.id to UUID + back-fill related_entity_id refs.
package signalrepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	domsignal "github.com/konoha-labs/insight-social/internal/domain/signal"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

// ---- writes ----

const insertSQL = `
INSERT INTO signals (
    author_id, match_id, kind, source, confidence, body, created_at
) VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING id
`

func (r *Repository) Insert(ctx context.Context, s *domsignal.Signal) error {
	if s.ID() != 0 {
		return errors.New("signalrepo: signal already has id (refusing to re-insert)")
	}
	var (
		bodyArg any
	)
	if s.Body() != "" {
		bodyArg = s.Body()
	} // else nil → NULL in TEXT column

	var newID int64
	err := r.pool.QueryRow(ctx, insertSQL,
		s.AuthorID(), s.MatchID(), s.Label(), s.Source().String(),
		s.Confidence(), bodyArg, s.Ts(),
	).Scan(&newID)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.ForeignKeyViolation {
			// author_id and match_id are FK. The constraint name
			// would tell us which one, but for the W2.1b error
			// surface we lump both into ErrAuthorNotFound /
			// ErrMatchNotFound based on a follow-up probe.
			switch pgErr.ConstraintName {
			case "signals_author_id_fkey":
				return domsignal.ErrAuthorNotFound
			case "signals_match_id_fkey":
				return domsignal.ErrMatchNotFound
			default:
				return fmt.Errorf("signalrepo insert fk: %w", err)
			}
		}
		return fmt.Errorf("signalrepo insert: %w", err)
	}
	s.SetID(newID)
	return nil
}

// ---- reads ----

const selectCols = `
id, author_id, match_id, kind, source, confidence, body, created_at
`

func (r *Repository) GetByID(ctx context.Context, id int64) (*domsignal.Signal, error) {
	return scanSignal(r.pool.QueryRow(ctx,
		`SELECT `+selectCols+` FROM signals WHERE id = $1`, id))
}

// Both List* queries use keyset on (created_at DESC, id DESC) for
// stable recent-first paging. Cursor codec is the message_cursor
// pattern (timestamp + bigint) — but we keep it private to this
// package since it's only used here.

const listForMatchSQL = `
SELECT ` + selectCols + `
  FROM signals
 WHERE match_id = $1
   AND ($3::timestamptz IS NULL OR (created_at, id) < ($3, $4::bigint))
 ORDER BY created_at DESC, id DESC
 LIMIT $2
`

func (r *Repository) ListForMatch(ctx context.Context, f domsignal.ListForMatchFilter) (domsignal.ListPage, error) {
	cursorTS, cursorID, err := decodeSignalCursor(f.Cursor)
	if err != nil {
		return domsignal.ListPage{}, err
	}
	return r.runList(ctx, listForMatchSQL, f.Limit, f.MatchID, cursorTS, cursorID)
}

const listForUserSQL = `
SELECT ` + selectCols + `
  FROM signals
 WHERE author_id = $1
   AND ($3::timestamptz IS NULL OR (created_at, id) < ($3, $4::bigint))
 ORDER BY created_at DESC, id DESC
 LIMIT $2
`

func (r *Repository) ListForUser(ctx context.Context, f domsignal.ListForUserFilter) (domsignal.ListPage, error) {
	cursorTS, cursorID, err := decodeSignalCursor(f.Cursor)
	if err != nil {
		return domsignal.ListPage{}, err
	}
	return r.runList(ctx, listForUserSQL, f.Limit, f.UserID, cursorTS, cursorID)
}

// runList is the shared paginated read body. Both List queries share
// the same column projection, cursor shape, and page assembly.
func (r *Repository) runList(ctx context.Context, sql string, limit int,
	scopeID uuid.UUID, cursorTS time.Time, cursorID int64) (domsignal.ListPage, error) {
	var tsArg, idArg any
	if !cursorTS.IsZero() {
		tsArg = cursorTS
		idArg = cursorID
	}

	rows, err := r.pool.Query(ctx, sql, scopeID, limit, tsArg, idArg)
	if err != nil {
		return domsignal.ListPage{}, fmt.Errorf("signalrepo list: %w", err)
	}
	defer rows.Close()

	out := make([]*domsignal.Signal, 0, limit)
	for rows.Next() {
		s, err := scanSignal(rows)
		if err != nil {
			return domsignal.ListPage{}, err
		}
		out = append(out, s)
	}
	if err := rows.Err(); err != nil {
		return domsignal.ListPage{}, fmt.Errorf("signalrepo list rows: %w", err)
	}

	page := domsignal.ListPage{Signals: out}
	if len(out) == limit {
		last := out[len(out)-1]
		page.NextCursor = encodeSignalCursor(last.Ts(), last.ID())
	}
	return page, nil
}

// ---- helpers ----

type rowScanner interface {
	Scan(dest ...any) error
}

func scanSignal(r rowScanner) (*domsignal.Signal, error) {
	var (
		id         int64
		authorID   uuid.UUID
		matchID    *uuid.UUID
		kind       string
		source     string
		confidence float64
		body       *string
		createdAt  time.Time
	)
	err := r.Scan(&id, &authorID, &matchID, &kind, &source, &confidence, &body, &createdAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, domsignal.ErrNotFound
		}
		return nil, fmt.Errorf("signalrepo scan: %w", err)
	}
	var (
		mID  uuid.UUID
		bStr string
	)
	if matchID != nil {
		mID = *matchID
	}
	if body != nil {
		bStr = *body
	}
	// State is always Pending — see package doc.
	return domsignal.Reconstitute(id, authorID, mID, domsignal.ParseSource(source),
		kind, bStr, confidence, domsignal.StatePending, createdAt.UTC()), nil
}
