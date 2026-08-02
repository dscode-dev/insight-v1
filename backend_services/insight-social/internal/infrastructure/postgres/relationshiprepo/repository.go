// Package relationshiprepo is the pgx-backed Relationship repository.
//
// Notes on pagination: relationships table has a BIGSERIAL id but
// we paginate on (created_at DESC, id DESC) using a reused cursor
// codec local to this package (signal-style).
package relationshiprepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	domrelationship "github.com/konoha-labs/insight-social/internal/domain/relationship"
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
INSERT INTO relationships (actor_id, target_id, kind, created_at)
VALUES ($1, $2, $3, NOW())
RETURNING actor_id, target_id, kind, created_at
`

func (r *Repository) Follow(ctx context.Context, actorID, targetID uuid.UUID) (*domrelationship.Relationship, error) {
	return r.insertEdge(ctx, actorID, targetID, domrelationship.KindFollow)
}

func (r *Repository) Unfollow(ctx context.Context, actorID, targetID uuid.UUID) error {
	cmd, err := r.pool.Exec(ctx,
		`DELETE FROM relationships WHERE actor_id = $1 AND target_id = $2 AND kind = 'follow'`,
		actorID, targetID,
	)
	if err != nil {
		return fmt.Errorf("relationshiprepo unfollow: %w", err)
	}
	if cmd.RowsAffected() == 0 {
		return domrelationship.ErrNotFound
	}
	return nil
}

// Block: 3 statements in one tx.
//  1. Remove any 'follow' edges in either direction (so a previously
//     mutual follow becomes a hard block on both sides).
//  2. Insert the 'block' edge from actor → target.
//  3. Return it.
//
// Wrapped in a transaction because partial failure between (1) and
// (2) would leave the user surprised ("I blocked them but they're
// still following me").
const removeFollowsBothWaysSQL = `
DELETE FROM relationships
 WHERE kind = 'follow'
   AND ((actor_id = $1 AND target_id = $2)
     OR (actor_id = $2 AND target_id = $1))
`

func (r *Repository) Block(ctx context.Context, actorID, targetID uuid.UUID) (*domrelationship.Relationship, error) {
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return nil, fmt.Errorf("relationshiprepo block begin: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }() // no-op if Commit succeeded

	if _, err := tx.Exec(ctx, removeFollowsBothWaysSQL, actorID, targetID); err != nil {
		return nil, fmt.Errorf("relationshiprepo block clear: %w", err)
	}

	rel := &domrelationship.Relationship{}
	var kindStr string
	err = tx.QueryRow(ctx, insertSQL,
		actorID, targetID, domrelationship.KindBlock.String(),
	).Scan(&rel.ActorID, &rel.TargetID, &kindStr, &rel.CreatedAt)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) {
			switch pgErr.Code {
			case pgerrcode.UniqueViolation:
				return nil, domrelationship.ErrAlreadyExists
			case pgerrcode.ForeignKeyViolation:
				return nil, domrelationship.ErrUserNotFound
			case pgerrcode.CheckViolation:
				return nil, domrelationship.ErrSelfTarget
			}
		}
		return nil, fmt.Errorf("relationshiprepo block insert: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("relationshiprepo block commit: %w", err)
	}
	rel.Kind = domrelationship.ParseKind(kindStr)
	rel.CreatedAt = rel.CreatedAt.UTC()
	return rel, nil
}

func (r *Repository) insertEdge(ctx context.Context, actorID, targetID uuid.UUID, kind domrelationship.Kind) (*domrelationship.Relationship, error) {
	rel := &domrelationship.Relationship{}
	var kindStr string
	err := r.pool.QueryRow(ctx, insertSQL, actorID, targetID, kind.String()).
		Scan(&rel.ActorID, &rel.TargetID, &kindStr, &rel.CreatedAt)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) {
			switch pgErr.Code {
			case pgerrcode.UniqueViolation:
				return nil, domrelationship.ErrAlreadyExists
			case pgerrcode.ForeignKeyViolation:
				return nil, domrelationship.ErrUserNotFound
			case pgerrcode.CheckViolation:
				return nil, domrelationship.ErrSelfTarget
			}
		}
		return nil, fmt.Errorf("relationshiprepo insert: %w", err)
	}
	rel.Kind = domrelationship.ParseKind(kindStr)
	rel.CreatedAt = rel.CreatedAt.UTC()
	return rel, nil
}

// ---- reads ----

const listFollowersSQL = `
SELECT id, actor_id, target_id, kind, created_at
  FROM relationships
 WHERE target_id = $1 AND kind = 'follow'
   AND ($3::timestamptz IS NULL OR (created_at, id) < ($3, $4::bigint))
 ORDER BY created_at DESC, id DESC
 LIMIT $2
`

func (r *Repository) ListFollowers(ctx context.Context, f domrelationship.ListFilter) (domrelationship.ListPage, error) {
	return r.runList(ctx, listFollowersSQL, f)
}

const listFollowingSQL = `
SELECT id, actor_id, target_id, kind, created_at
  FROM relationships
 WHERE actor_id = $1 AND kind = 'follow'
   AND ($3::timestamptz IS NULL OR (created_at, id) < ($3, $4::bigint))
 ORDER BY created_at DESC, id DESC
 LIMIT $2
`

func (r *Repository) ListFollowing(ctx context.Context, f domrelationship.ListFilter) (domrelationship.ListPage, error) {
	return r.runList(ctx, listFollowingSQL, f)
}

// runList: select the bigserial `id` only to feed the next-cursor.
// The domain Relationship never exposes it (graph edges are
// identified by (actor, target, kind), not by surrogate pk).
func (r *Repository) runList(ctx context.Context, sql string, f domrelationship.ListFilter) (domrelationship.ListPage, error) {
	cursorTS, cursorID, err := decodeRelCursor(f.Cursor)
	if err != nil {
		return domrelationship.ListPage{}, err
	}
	var tsArg, idArg any
	if !cursorTS.IsZero() {
		tsArg = cursorTS
		idArg = cursorID
	}

	rows, err := r.pool.Query(ctx, sql, f.UserID, f.Limit, tsArg, idArg)
	if err != nil {
		return domrelationship.ListPage{}, fmt.Errorf("relationshiprepo list: %w", err)
	}
	defer rows.Close()

	out := make([]*domrelationship.Relationship, 0, f.Limit)
	var lastInternalID int64
	for rows.Next() {
		var (
			internalID        int64
			actorID, targetID uuid.UUID
			kindStr           string
			createdAt         time.Time
		)
		if err := rows.Scan(&internalID, &actorID, &targetID, &kindStr, &createdAt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				break
			}
			return domrelationship.ListPage{}, fmt.Errorf("relationshiprepo scan: %w", err)
		}
		lastInternalID = internalID
		out = append(out, &domrelationship.Relationship{
			ActorID:   actorID,
			TargetID:  targetID,
			Kind:      domrelationship.ParseKind(kindStr),
			CreatedAt: createdAt.UTC(),
		})
	}
	if err := rows.Err(); err != nil {
		return domrelationship.ListPage{}, fmt.Errorf("relationshiprepo list rows: %w", err)
	}

	page := domrelationship.ListPage{Relationships: out}
	if len(out) == f.Limit {
		last := out[len(out)-1]
		page.NextCursor = encodeRelCursor(last.CreatedAt, lastInternalID)
	}
	return page, nil
}

// ---- Sprint 3 (Social Foundation): mute + feed-graph queries ----

const muteSQL = `
UPDATE relationships
SET muted = $3, muted_at = CASE WHEN $3 THEN NOW() ELSE NULL END
WHERE actor_id = $1 AND target_id = $2 AND kind = 'follow'
RETURNING actor_id, target_id, kind, created_at, muted, muted_at
`

func (r *Repository) Mute(ctx context.Context, actorID, targetID uuid.UUID) (*domrelationship.Relationship, error) {
	return r.setMuted(ctx, actorID, targetID, true)
}

func (r *Repository) Unmute(ctx context.Context, actorID, targetID uuid.UUID) (*domrelationship.Relationship, error) {
	return r.setMuted(ctx, actorID, targetID, false)
}

func (r *Repository) setMuted(ctx context.Context, actorID, targetID uuid.UUID, muted bool) (*domrelationship.Relationship, error) {
	rel := &domrelationship.Relationship{}
	var kindStr string
	err := r.pool.QueryRow(ctx, muteSQL, actorID, targetID, muted).
		Scan(&rel.ActorID, &rel.TargetID, &kindStr, &rel.CreatedAt, &rel.Muted, &rel.MutedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, domrelationship.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("relationshiprepo set_muted: %w", err)
	}
	rel.Kind = domrelationship.ParseKind(kindStr)
	rel.CreatedAt = rel.CreatedAt.UTC()
	return rel, nil
}

// FollowIdempotent creates the follow edge if absent; an existing
// edge is a no-op (ON CONFLICT DO NOTHING) — replay-safe, used by
// automatic agent following.
func (r *Repository) FollowIdempotent(ctx context.Context, actorID, targetID uuid.UUID) error {
	_, err := r.pool.Exec(ctx, `
INSERT INTO relationships (actor_id, target_id, kind, created_at)
VALUES ($1, $2, 'follow', NOW())
ON CONFLICT (actor_id, target_id, kind) DO NOTHING`,
		actorID, targetID,
	)
	if err != nil {
		return fmt.Errorf("relationshiprepo follow_idempotent: %w", err)
	}
	return nil
}

// FollowingIDs returns who the user follows. excludeMuted=true is
// the feed path's view: muted accounts remain followed but never
// reach a feed.
func (r *Repository) FollowingIDs(ctx context.Context, userID uuid.UUID, excludeMuted bool) ([]uuid.UUID, error) {
	query := `SELECT target_id FROM relationships WHERE actor_id = $1 AND kind = 'follow'`
	if excludeMuted {
		query += ` AND muted = FALSE`
	}
	rows, err := r.pool.Query(ctx, query, userID)
	if err != nil {
		return nil, fmt.Errorf("relationshiprepo following_ids: %w", err)
	}
	defer rows.Close()
	var ids []uuid.UUID
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("relationshiprepo following_ids scan: %w", err)
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}
