// Package reactionrepo — pgx-backed Reaction repository (Sprint B).
//
// Idempotency:
//   - React  — ON CONFLICT DO NOTHING + RETURNING via a CTE so the
//     caller always gets back the row, whether it's the new
//     insert or the pre-existing one.
//   - Unreact — DELETE WHERE returns 0 rows when there's nothing to
//     delete; we map that to nil error (no-op semantics).
//
// State queries:
//   - StateForDiscussion uses ONE round-trip with two scalar subselects
//     (COUNT + EXISTS) so the BFF can populate the heart button in a
//     single call.
//   - BatchStateForDiscussions returns one row per requested id with
//     LEFT JOIN — unknown ids surface as (count=0, liked=false) rather
//     than missing entries, so the BFF can zip the slice safely.
package reactionrepo

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	domreaction "github.com/konoha-labs/insight-social/internal/domain/reaction"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

// React: idempotent insert. The CTE pattern returns the row whether
// the INSERT did fire or hit the unique constraint.
const reactSQL = `
WITH ins AS (
    INSERT INTO reactions (user_id, discussion_id, kind)
    VALUES ($1, $2, $3)
    ON CONFLICT (user_id, discussion_id, kind) DO NOTHING
    RETURNING user_id, discussion_id, kind, created_at
)
SELECT user_id, discussion_id, kind, created_at FROM ins
UNION ALL
SELECT user_id, discussion_id, kind, created_at
  FROM reactions
 WHERE user_id = $1 AND discussion_id = $2 AND kind = $3
   AND NOT EXISTS (SELECT 1 FROM ins)
LIMIT 1
`

func (r *Repository) React(ctx context.Context, userID, discussionID uuid.UUID, kind domreaction.Kind) (*domreaction.Reaction, error) {
	rec := &domreaction.Reaction{}
	var kindStr string
	err := r.pool.QueryRow(ctx, reactSQL, userID, discussionID, kind.String()).Scan(
		&rec.UserID, &rec.DiscussionID, &kindStr, &rec.CreatedAt,
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.ForeignKeyViolation {
			switch pgErr.ConstraintName {
			case "reactions_discussion_id_fkey":
				return nil, domreaction.ErrDiscussionNotFound
			case "reactions_user_id_fkey":
				return nil, domreaction.ErrUserNotFound
			}
		}
		return nil, fmt.Errorf("reactionrepo react: %w", err)
	}
	rec.Kind = domreaction.ParseKind(kindStr)
	rec.CreatedAt = rec.CreatedAt.UTC()
	return rec, nil
}

// Unreact: idempotent delete. Missing row → no error.
const unreactSQL = `
DELETE FROM reactions
 WHERE user_id = $1 AND discussion_id = $2 AND kind = $3
`

func (r *Repository) Unreact(ctx context.Context, userID, discussionID uuid.UUID, kind domreaction.Kind) error {
	_, err := r.pool.Exec(ctx, unreactSQL, userID, discussionID, kind.String())
	if err != nil {
		return fmt.Errorf("reactionrepo unreact: %w", err)
	}
	return nil
}

// StateForDiscussion: one round-trip, two scalar subselects.
// `$2::uuid` allows passing uuid.Nil → liked_by_user always false
// (the EXISTS filter doesn't match).
const stateForDiscussionSQL = `
SELECT
  (SELECT COUNT(*) FROM reactions WHERE discussion_id = $1 AND kind = 'like') AS like_count,
  EXISTS (
      SELECT 1 FROM reactions
       WHERE discussion_id = $1 AND user_id = $2 AND kind = 'like'
  ) AS liked_by_user
`

func (r *Repository) StateForDiscussion(ctx context.Context, discussionID, viewerID uuid.UUID) (domreaction.DiscussionState, error) {
	var s domreaction.DiscussionState
	s.DiscussionID = discussionID
	err := r.pool.QueryRow(ctx, stateForDiscussionSQL, discussionID, viewerID).Scan(
		&s.LikeCount, &s.LikedByUser,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// Shouldn't happen — the query always returns one row.
			return s, nil
		}
		return s, fmt.Errorf("reactionrepo state: %w", err)
	}
	return s, nil
}

// BatchStateForDiscussions: one query, one row per input id. LEFT JOIN
// against a GROUP BY-counted derived table so unknown ids surface as
// (count=0, liked=false).
const batchStateSQL = `
WITH wanted AS (
    SELECT id FROM UNNEST($1::uuid[]) AS id
), counts AS (
    SELECT discussion_id, COUNT(*) AS like_count
      FROM reactions
     WHERE kind = 'like' AND discussion_id = ANY($1::uuid[])
     GROUP BY discussion_id
), viewer AS (
    SELECT discussion_id
      FROM reactions
     WHERE kind = 'like' AND user_id = $2 AND discussion_id = ANY($1::uuid[])
)
SELECT w.id,
       COALESCE(c.like_count, 0)         AS like_count,
       (v.discussion_id IS NOT NULL)     AS liked_by_user
  FROM wanted w
  LEFT JOIN counts c ON c.discussion_id = w.id
  LEFT JOIN viewer v ON v.discussion_id = w.id
`

func (r *Repository) BatchStateForDiscussions(ctx context.Context, discussionIDs []uuid.UUID, viewerID uuid.UUID) ([]domreaction.DiscussionState, error) {
	rows, err := r.pool.Query(ctx, batchStateSQL, discussionIDs, viewerID)
	if err != nil {
		return nil, fmt.Errorf("reactionrepo batch state: %w", err)
	}
	defer rows.Close()

	out := make([]domreaction.DiscussionState, 0, len(discussionIDs))
	for rows.Next() {
		var s domreaction.DiscussionState
		if err := rows.Scan(&s.DiscussionID, &s.LikeCount, &s.LikedByUser); err != nil {
			return nil, fmt.Errorf("reactionrepo batch scan: %w", err)
		}
		out = append(out, s)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("reactionrepo batch rows: %w", err)
	}
	return out, nil
}
