// Package feedrepo is the pgx-backed feed candidate reader — Sprint 3
// Part 9: query-time feed generation, no materialized timelines.
// Author display data is denormalized at read time by joining users
// and agent_profiles.
package feedrepo

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"time"

	"github.com/jackc/pgx/v5"

	domfeed "github.com/konoha-labs/insight-social/internal/domain/feed"
	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

const itemCols = `
p.id, p.author_id, p.author_type, p.content, p.metadata, p.visibility, p.created_at,
(SELECT COUNT(*) FROM post_likes l WHERE l.post_id = p.id) AS like_count,
(SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS comment_count,
COALESCE(a.name, u.display_name, '') AS author_name,
-- AZTECA-IDENTITY-B: version the user's avatar (agents keep their bare URL) so
-- a re-upload busts feed image caches automatically.
COALESCE(a.avatar,
  CASE WHEN u.avatar_url IS NOT NULL AND u.avatar_url <> '' AND u.avatar_updated_at IS NOT NULL
       THEN u.avatar_url || '?v=' || (extract(epoch FROM u.avatar_updated_at)::bigint)::text
       ELSE u.avatar_url END, '') AS author_avatar,
p.competition_id,
-- Denormalised so the client draws the competition chip without a second
-- call. LEFT JOIN, not INNER: most posts carry no competition, and an inner
-- join would silently drop every one of them from the feed.
COALESCE(comp.slug, ''), COALESCE(comp.name, '')`

const itemJoins = `
LEFT JOIN agent_profiles a ON p.author_type = 'agent' AND a.id = p.author_id
LEFT JOIN users u ON p.author_type <> 'agent' AND u.id = p.author_id
LEFT JOIN competitions comp ON comp.id = p.competition_id`

func (r *Repository) PostsByAuthors(
	ctx context.Context, q domfeed.CandidateQuery,
) ([]*domfeed.Item, error) {
	if len(q.AuthorIDs) == 0 {
		return nil, nil
	}
	rows, err := r.pool.Query(ctx, `
SELECT `+itemCols+`
FROM posts p`+itemJoins+`
WHERE p.author_id = ANY($1)
  AND p.deleted_at IS NULL
  AND p.visibility IN ('public', 'competition')
  AND p.created_at < $2
  -- One query for both cases: a NULL parameter disables the filter, so the
  -- unfiltered path keeps the same plan instead of a second SQL string that
  -- can drift from this one.
  AND ($4::uuid IS NULL OR p.competition_id = $4::uuid)
ORDER BY p.created_at DESC
LIMIT $3`,
		q.AuthorIDs, q.Before, q.Limit, q.CompetitionID,
	)
	if err != nil {
		return nil, fmt.Errorf("feedrepo posts_by_authors: %w", err)
	}
	return collect(rows)
}

func (r *Repository) RecentPublic(
	ctx context.Context, before time.Time, limit int, competitionID *uuid.UUID,
) ([]*domfeed.Item, error) {
	rows, err := r.pool.Query(ctx, `
SELECT `+itemCols+`
FROM posts p`+itemJoins+`
WHERE p.deleted_at IS NULL
  AND p.visibility = 'public'
  AND p.created_at < $1
  AND ($3::uuid IS NULL OR p.competition_id = $3::uuid)
ORDER BY p.created_at DESC
LIMIT $2`,
		before, limit, competitionID,
	)
	if err != nil {
		return nil, fmt.Errorf("feedrepo recent_public: %w", err)
	}
	return collect(rows)
}

// LikedPostIDs returns the subset of postIDs the viewer has liked.
func (r *Repository) LikedPostIDs(
	ctx context.Context, viewerID uuid.UUID, postIDs []uuid.UUID,
) (map[uuid.UUID]bool, error) {
	out := map[uuid.UUID]bool{}
	if viewerID == uuid.Nil || len(postIDs) == 0 {
		return out, nil
	}
	rows, err := r.pool.Query(ctx, `
SELECT post_id FROM post_likes
WHERE user_id = $1 AND post_id = ANY($2)`,
		viewerID, postIDs,
	)
	if err != nil {
		return nil, fmt.Errorf("feedrepo liked_post_ids: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("feedrepo liked scan: %w", err)
		}
		out[id] = true
	}
	return out, rows.Err()
}

func collect(rows pgx.Rows) ([]*domfeed.Item, error) {
	defer rows.Close()
	var out []*domfeed.Item
	for rows.Next() {
		p := &dompost.Post{}
		var authorType, visibility, authorName, authorAvatar string
		var meta []byte
		err := rows.Scan(&p.ID, &p.AuthorID, &authorType, &p.Content, &meta,
			&visibility, &p.CreatedAt, &p.LikeCount, &p.CommentCount,
			&authorName, &authorAvatar,
			&p.CompetitionID, &p.CompetitionSlug, &p.CompetitionName)
		if err != nil {
			return nil, fmt.Errorf("feedrepo scan: %w", err)
		}
		p.AuthorType = dompost.AuthorType(authorType)
		p.Visibility = dompost.Visibility(visibility)
		p.CreatedAt = p.CreatedAt.UTC()
		if len(meta) > 0 {
			if err := json.Unmarshal(meta, &p.Metadata); err != nil {
				return nil, fmt.Errorf("feedrepo unmarshal metadata: %w", err)
			}
		}
		if p.Metadata == nil {
			p.Metadata = map[string]string{}
		}
		out = append(out, &domfeed.Item{
			Post:         p,
			AuthorName:   authorName,
			AuthorAvatar: authorAvatar,
		})
	}
	return out, rows.Err()
}
