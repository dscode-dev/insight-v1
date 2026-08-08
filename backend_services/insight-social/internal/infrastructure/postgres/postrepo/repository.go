// Package postrepo is the pgx-backed repository for the post
// aggregate: posts (soft-deleted), comments (depth-limited) and
// likes (idempotent).
package postrepo

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

// ---- posts ----

func (r *Repository) InsertPost(ctx context.Context, p *dompost.Post) error {
	meta, err := json.Marshal(p.Metadata)
	if err != nil {
		return fmt.Errorf("postrepo marshal metadata: %w", err)
	}
	_, err = r.pool.Exec(ctx, `
INSERT INTO posts (id, author_id, author_type, content, metadata, visibility, created_at, competition_id)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
		p.ID, p.AuthorID, string(p.AuthorType), p.Content, meta,
		string(p.Visibility), p.CreatedAt, p.CompetitionID,
	)
	if err != nil {
		// 23503 is posts_competition_id_fkey: the post names a competition
		// that is not in the registry. Reported as the domain's "unknown"
		// rather than a wrapped driver error, because the caller's answer is
		// a 400 naming the field, not a 500.
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23503" &&
			strings.Contains(pgErr.ConstraintName, "competition") {
			return dompost.ErrCompetitionUnknown
		}
		return fmt.Errorf("postrepo insert: %w", err)
	}
	return nil
}

const postCols = `
p.id, p.author_id, p.author_type, p.content, p.metadata, p.visibility, p.created_at,
(SELECT COUNT(*) FROM post_likes l WHERE l.post_id = p.id) AS like_count,
(SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS comment_count,
(SELECT COUNT(*) FROM post_shares s WHERE s.post_id = p.id) AS share_count,
p.competition_id,
-- Denormalised on read so the client can draw the competition chip without a
-- second call. LEFT JOIN, not INNER: most posts carry no competition, and an
-- inner join would silently drop them from every result.
COALESCE(comp.slug, ''), COALESCE(comp.name, '')`

const postJoins = `
LEFT JOIN competitions comp ON comp.id = p.competition_id`

func (r *Repository) GetPost(ctx context.Context, id uuid.UUID) (*dompost.Post, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+postCols+` FROM posts p`+postJoins+` WHERE p.id = $1 AND p.deleted_at IS NULL`, id)
	p, err := scanPost(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, dompost.ErrNotFound
	}
	return p, err
}

// SoftDeletePost marks the post deleted, author-only (audit trail
// preserved — the row survives).
func (r *Repository) SoftDeletePost(ctx context.Context, id, requesterID uuid.UUID) error {
	cmd, err := r.pool.Exec(ctx, `
UPDATE posts SET deleted_at = NOW()
WHERE id = $1 AND author_id = $2 AND deleted_at IS NULL`,
		id, requesterID,
	)
	if err != nil {
		return fmt.Errorf("postrepo soft_delete: %w", err)
	}
	if cmd.RowsAffected() == 0 {
		// Distinguish "missing" from "not yours".
		var exists bool
		if err := r.pool.QueryRow(ctx,
			`SELECT TRUE FROM posts WHERE id = $1 AND deleted_at IS NULL`, id,
		).Scan(&exists); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return dompost.ErrNotFound
			}
			return fmt.Errorf("postrepo soft_delete check: %w", err)
		}
		return dompost.ErrNotAuthor
	}
	return nil
}

func scanPost(row pgx.Row) (*dompost.Post, error) {
	p := &dompost.Post{}
	var authorType, visibility string
	var meta []byte
	err := row.Scan(&p.ID, &p.AuthorID, &authorType, &p.Content, &meta,
		&visibility, &p.CreatedAt, &p.LikeCount, &p.CommentCount, &p.ShareCount,
		&p.CompetitionID, &p.CompetitionSlug, &p.CompetitionName)
	if err != nil {
		return nil, err
	}
	p.AuthorType = dompost.AuthorType(authorType)
	p.Visibility = dompost.Visibility(visibility)
	p.CreatedAt = p.CreatedAt.UTC()
	if len(meta) > 0 {
		if err := json.Unmarshal(meta, &p.Metadata); err != nil {
			return nil, fmt.Errorf("postrepo unmarshal metadata: %w", err)
		}
	}
	if p.Metadata == nil {
		p.Metadata = map[string]string{}
	}
	return p, nil
}

// ---- comments ----

func (r *Repository) InsertComment(ctx context.Context, c *dompost.Comment) error {
	_, err := r.pool.Exec(ctx, `
INSERT INTO comments (id, post_id, parent_id, author_id, author_type, content, depth, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
		c.ID, c.PostID, c.ParentID, c.AuthorID, string(c.AuthorType),
		c.Content, c.Depth, c.CreatedAt,
	)
	if err != nil {
		return fmt.Errorf("postrepo insert_comment: %w", err)
	}
	return nil
}

const commentCols = `id, post_id, parent_id, author_id, author_type, content, depth, created_at`

func (r *Repository) GetComment(ctx context.Context, id uuid.UUID) (*dompost.Comment, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+commentCols+` FROM comments WHERE id = $1`, id)
	c, err := scanComment(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, dompost.ErrCommentNotFound
	}
	return c, err
}

func (r *Repository) ListComments(
	ctx context.Context, postID uuid.UUID, limit int, cursor string,
) (dompost.CommentPage, error) {
	before := decodeTimeCursor(cursor)
	rows, err := r.pool.Query(ctx, `
SELECT `+commentCols+` FROM comments
WHERE post_id = $1 AND created_at < $2
ORDER BY created_at ASC, id ASC
LIMIT $3`,
		postID, before, limit+1,
	)
	if err != nil {
		return dompost.CommentPage{}, fmt.Errorf("postrepo list_comments: %w", err)
	}
	defer rows.Close()
	var out []*dompost.Comment
	for rows.Next() {
		c, err := scanComment(rows)
		if err != nil {
			return dompost.CommentPage{}, err
		}
		out = append(out, c)
	}
	if err := rows.Err(); err != nil {
		return dompost.CommentPage{}, err
	}
	page := dompost.CommentPage{Comments: out}
	if len(out) > limit {
		page.Comments = out[:limit]
	}
	return page, nil
}

func scanComment(row pgx.Row) (*dompost.Comment, error) {
	c := &dompost.Comment{}
	var authorType string
	err := row.Scan(&c.ID, &c.PostID, &c.ParentID, &c.AuthorID,
		&authorType, &c.Content, &c.Depth, &c.CreatedAt)
	if err != nil {
		return nil, err
	}
	c.AuthorType = dompost.AuthorType(authorType)
	c.CreatedAt = c.CreatedAt.UTC()
	return c, nil
}

// ---- likes ----

// Like is idempotent: re-liking is a DB-level no-op (replay-safe).
func (r *Repository) Like(ctx context.Context, postID, userID uuid.UUID) error {
	if _, err := r.GetPost(ctx, postID); err != nil {
		return err
	}
	_, err := r.pool.Exec(ctx, `
INSERT INTO post_likes (post_id, user_id, created_at)
VALUES ($1, $2, NOW())
ON CONFLICT (post_id, user_id) DO NOTHING`,
		postID, userID,
	)
	if err != nil {
		return fmt.Errorf("postrepo like: %w", err)
	}
	return nil
}

func (r *Repository) Unlike(ctx context.Context, postID, userID uuid.UUID) error {
	_, err := r.pool.Exec(ctx,
		`DELETE FROM post_likes WHERE post_id = $1 AND user_id = $2`,
		postID, userID,
	)
	if err != nil {
		return fmt.Errorf("postrepo unlike: %w", err)
	}
	return nil
}

func decodeTimeCursor(cursor string) time.Time {
	if cursor == "" {
		return time.Now().UTC().Add(time.Minute)
	}
	raw, err := base64.RawURLEncoding.DecodeString(cursor)
	if err != nil {
		return time.Now().UTC().Add(time.Minute)
	}
	nanos, err := strconv.ParseInt(string(raw), 10, 64)
	if err != nil {
		return time.Now().UTC().Add(time.Minute)
	}
	return time.Unix(0, nanos).UTC()
}

// ---- shares -----------------------------------------------------------------
//
// Two kinds behind one table, told apart by `target` — see migration 00014.
// A repost is a STATE (unique per user and post, toggled by a button); an
// external share is an EVENT (the same person sends the same post twice, and
// both count).

// Share records one share and returns whether a row was created plus the
// post's resulting count.
//
// `created` is false when a repost already existed. Without it the caller
// cannot tell "done" from "already done", and a client would animate a state
// change that never happened.
func (r *Repository) Share(
	ctx context.Context, postID, userID uuid.UUID, target, channel string,
) (created bool, count int64, err error) {
	// A share of a deleted post would satisfy the foreign key (the row
	// survives a soft delete) while referring to something no reader can see.
	if _, err := r.GetPost(ctx, postID); err != nil {
		return false, 0, err
	}

	var chanArg *string
	if target == dompost.ShareExternal && channel != "" {
		chanArg = &channel
	}

	// ON CONFLICT targets the PARTIAL unique index, so it applies to reposts
	// and leaves external shares free to repeat. `RETURNING` fires only on a
	// real insert, which is exactly the signal `created` needs — checking
	// beforehand would race with a concurrent tap on the same button.
	var inserted uuid.UUID
	scanErr := r.pool.QueryRow(ctx, `
INSERT INTO post_shares (post_id, user_id, target, channel)
VALUES ($1, $2, $3, $4)
ON CONFLICT (user_id, post_id) WHERE target = 'feed' DO NOTHING
RETURNING id`,
		postID, userID, target, chanArg,
	).Scan(&inserted)

	switch {
	case scanErr == nil:
		created = true
	case errors.Is(scanErr, pgx.ErrNoRows):
		// The repost was already there. Not an error: the button is a toggle
		// and the user's intent is satisfied either way.
		created = false
	default:
		return false, 0, fmt.Errorf("postrepo share: %w", scanErr)
	}

	count, err = r.ShareCount(ctx, postID)
	if err != nil {
		return created, 0, err
	}
	return created, count, nil
}

// Unshare removes the caller's repost. External shares are not removable —
// they describe something that already happened outside the platform.
func (r *Repository) Unshare(ctx context.Context, postID, userID uuid.UUID) error {
	_, err := r.pool.Exec(ctx,
		`DELETE FROM post_shares
		  WHERE post_id = $1 AND user_id = $2 AND target = 'feed'`,
		postID, userID,
	)
	if err != nil {
		return fmt.Errorf("postrepo unshare: %w", err)
	}
	return nil
}

// ShareCount sums BOTH kinds. "Compartilhamentos" beside a post means how many
// times it travelled, and a reader does not distinguish the two.
func (r *Repository) ShareCount(ctx context.Context, postID uuid.UUID) (int64, error) {
	var count int64
	if err := r.pool.QueryRow(ctx,
		`SELECT count(*) FROM post_shares WHERE post_id = $1`, postID,
	).Scan(&count); err != nil {
		return 0, fmt.Errorf("postrepo share_count: %w", err)
	}
	return count, nil
}
