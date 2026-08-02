// Package searchrepo is the pgx-backed Search repository (FEATURE-SEARCH-V1
// Stage 1). One query path per category — deterministic bucket ranking computed
// in a CTE, explicit keyset pagination over the FULL sort key (bucket +
// category tiebreakers + id), parameterized SQL only, LIKE metacharacters
// escaped by the domain before any pattern is composed.
//
// Visibility rules Social OWNS are enforced here (public + non-deleted posts,
// active agents, active competitions). Gateway-owned moderation (hidden
// content, banned/suspended authors) is applied by the Gateway lens in Stage 2
// — the same split the feed uses.
//
// Every query fetches limit+1 rows: the overflow row proves another page
// exists; the next-cursor is built from the LAST KEPT row's full sort key.
package searchrepo

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	domsearch "github.com/konoha-labs/insight-social/internal/domain/search"
)

type Repository struct{ pool *pgxpool.Pool }

func New(pool *pgxpool.Pool) *Repository { return &Repository{pool: pool} }

// likePatterns derives exact/prefix/contains patterns from an ALREADY
// NORMALIZED query, with LIKE metacharacters escaped (wildcard-abuse-proof).
func likePatterns(q string) (exact, prefix, contains string) {
	esc := domsearch.EscapeLike(q)
	return q, esc + "%", "%" + esc + "%"
}

func encTime(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }
func encFloat(f float64) string  { return strconv.FormatFloat(f, 'g', -1, 64) }

// keyed pairs a result with the cursor that resumes AFTER it.
type keyed[T any] struct {
	item T
	cur  domsearch.Cursor
}

// pageOut trims the limit+1 fetch to limit and, when the overflow row proved
// more pages exist, emits the last kept row's cursor.
func pageOut[T any](rows []keyed[T], limit int) domsearch.Page[T] {
	var p domsearch.Page[T]
	more := len(rows) > limit
	if more {
		rows = rows[:limit]
	}
	p.Items = make([]T, 0, len(rows))
	for _, r := range rows {
		p.Items = append(p.Items, r.item)
	}
	if more && len(rows) > 0 {
		p.NextCursor = rows[len(rows)-1].cur.Encode()
	}
	return p
}

// ---------------------------------------------------------------------------
// USERS — bucket: 0 exact username · 1 username prefix · 2 display-name prefix
// · 3 contains / initials-exact. Tiebreak: reputation DESC, id ASC.
// ---------------------------------------------------------------------------

const userAvatarExpr = `CASE
    WHEN u.avatar_url IS NOT NULL AND u.avatar_url <> '' AND u.avatar_updated_at IS NOT NULL
    THEN u.avatar_url || '?v=' || (extract(epoch FROM u.avatar_updated_at)::bigint)::text
    ELSE u.avatar_url END`

func (r *Repository) SearchUsers(
	ctx context.Context, viewerID uuid.UUID, q string, limit int, cur *domsearch.Cursor,
) (domsearch.Page[domsearch.UserResult], error) {
	exact, prefix, contains := likePatterns(q)
	keyset, args := "TRUE", []any{exact, prefix, contains, viewerID}
	if cur != nil {
		rep, err := strconv.Atoi(cur.S1)
		if err != nil {
			return domsearch.Page[domsearch.UserResult]{}, domsearch.ErrInvalidCursor
		}
		args = append(args, cur.B, rep, cur.ID)
		keyset = `(bucket > $5 OR (bucket = $5 AND reputation < $6)
		           OR (bucket = $5 AND reputation = $6 AND id > $7::uuid))`
	}
	args = append(args, limit+1)
	sql := fmt.Sprintf(`
WITH ranked AS (
  SELECT u.id, u.username, u.display_name, u.initials, u.accent_color,
         `+userAvatarExpr+` AS avatar_url, u.reputation, u.tier,
         (SELECT COUNT(*) FROM relationships f WHERE f.target_id = u.id AND f.kind = 'follow') AS followers,
         EXISTS (SELECT 1 FROM relationships f WHERE f.actor_id = $4 AND f.target_id = u.id AND f.kind = 'follow') AS is_following,
         EXISTS (SELECT 1 FROM relationships f WHERE f.actor_id = u.id AND f.target_id = $4 AND f.kind = 'follow') AS follows_viewer,
         CASE
           WHEN lower(u.username) = $1 THEN 0
           WHEN lower(u.username) LIKE $2 ESCAPE '\' THEN 1
           WHEN lower(u.display_name) LIKE $2 ESCAPE '\' THEN 2
           ELSE 3
         END AS bucket
    FROM users u
   WHERE lower(u.username) LIKE $3 ESCAPE '\'
      OR lower(u.display_name) LIKE $3 ESCAPE '\'
      OR lower(u.initials) = $1
)
SELECT id, username, display_name, initials, accent_color, avatar_url,
       reputation, tier, followers, is_following, follows_viewer, bucket
  FROM ranked WHERE %s
 ORDER BY bucket, reputation DESC, id
 LIMIT $%d`, keyset, len(args))

	rows, err := r.pool.Query(ctx, sql, args...)
	if err != nil {
		return domsearch.Page[domsearch.UserResult]{}, fmt.Errorf("searchrepo users: %w", err)
	}
	defer rows.Close()

	var out []keyed[domsearch.UserResult]
	for rows.Next() {
		var it domsearch.UserResult
		var bucket int
		if err := rows.Scan(&it.ID, &it.Username, &it.DisplayName, &it.Initials,
			&it.AccentColor, &it.AvatarURL, &it.Reputation, &it.Tier,
			&it.Followers, &it.IsFollowing, &it.FollowsViewer, &bucket); err != nil {
			return domsearch.Page[domsearch.UserResult]{}, err
		}
		out = append(out, keyed[domsearch.UserResult]{it, domsearch.Cursor{
			Cat: string(domsearch.CategoryUsers), B: bucket,
			S1: strconv.Itoa(it.Reputation), ID: it.ID.String(),
		}})
	}
	if err := rows.Err(); err != nil {
		return domsearch.Page[domsearch.UserResult]{}, err
	}
	return pageOut(out, limit), nil
}

// ---------------------------------------------------------------------------
// AGENTS — active only. bucket: 0 exact slug · 1 name prefix · 2 name contains
// · 3 bio contains. Tiebreak: name ASC, id ASC.
// ---------------------------------------------------------------------------

func (r *Repository) SearchAgents(
	ctx context.Context, q string, limit int, cur *domsearch.Cursor,
) (domsearch.Page[domsearch.AgentResult], error) {
	exact, prefix, contains := likePatterns(q)
	keyset, args := "TRUE", []any{exact, prefix, contains}
	if cur != nil {
		args = append(args, cur.B, cur.S1, cur.ID)
		keyset = `(bucket > $4 OR (bucket = $4 AND name > $5)
		           OR (bucket = $4 AND name = $5 AND id > $6::uuid))`
	}
	args = append(args, limit+1)
	sql := fmt.Sprintf(`
WITH ranked AS (
  SELECT a.id, a.slug, a.name, a.avatar, a.bio, a.active, a.verified,
         CASE
           WHEN lower(a.slug) = $1 THEN 0
           WHEN lower(a.name) LIKE $2 ESCAPE '\' THEN 1
           WHEN lower(a.name) LIKE $3 ESCAPE '\' THEN 2
           ELSE 3
         END AS bucket
    FROM agent_profiles a
   WHERE a.active = TRUE
     AND (lower(a.slug) = $1
       OR lower(a.name) LIKE $3 ESCAPE '\'
       OR lower(a.bio) LIKE $3 ESCAPE '\')
)
SELECT id, slug, name, avatar, bio, active, verified, bucket
  FROM ranked WHERE %s
 ORDER BY bucket, name, id
 LIMIT $%d`, keyset, len(args))

	rows, err := r.pool.Query(ctx, sql, args...)
	if err != nil {
		return domsearch.Page[domsearch.AgentResult]{}, fmt.Errorf("searchrepo agents: %w", err)
	}
	defer rows.Close()

	var out []keyed[domsearch.AgentResult]
	for rows.Next() {
		var it domsearch.AgentResult
		var bucket int
		if err := rows.Scan(&it.ID, &it.Slug, &it.Name, &it.Avatar, &it.Bio,
			&it.Active, &it.Verified, &bucket); err != nil {
			return domsearch.Page[domsearch.AgentResult]{}, err
		}
		out = append(out, keyed[domsearch.AgentResult]{it, domsearch.Cursor{
			Cat: string(domsearch.CategoryAgents), B: bucket,
			S1: it.Name, ID: it.ID.String(),
		}})
	}
	if err := rows.Err(); err != nil {
		return domsearch.Page[domsearch.AgentResult]{}, err
	}
	return pageOut(out, limit), nil
}

// ---------------------------------------------------------------------------
// COMMUNITIES — bucket: 0 exact slug · 1 name prefix · 2 name contains ·
// 3 topic contains. Tiebreak: member_count DESC (real column), id ASC.
// Only real fields — no invented activity/relevance score.
// ---------------------------------------------------------------------------

func (r *Repository) SearchCommunities(
	ctx context.Context, q string, limit int, cur *domsearch.Cursor,
) (domsearch.Page[domsearch.CommunityResult], error) {
	exact, prefix, contains := likePatterns(q)
	keyset, args := "TRUE", []any{exact, prefix, contains}
	if cur != nil {
		mc, err := strconv.Atoi(cur.S1)
		if err != nil {
			return domsearch.Page[domsearch.CommunityResult]{}, domsearch.ErrInvalidCursor
		}
		args = append(args, cur.B, mc, cur.ID)
		keyset = `(bucket > $4 OR (bucket = $4 AND member_count < $5)
		           OR (bucket = $4 AND member_count = $5 AND id > $6::uuid))`
	}
	args = append(args, limit+1)
	sql := fmt.Sprintf(`
WITH ranked AS (
  SELECT c.id, c.slug, c.name, c.topic, c.kind, c.member_count, c.accent_color,
         CASE
           WHEN lower(c.slug) = $1 THEN 0
           WHEN lower(c.name) LIKE $2 ESCAPE '\' THEN 1
           WHEN lower(c.name) LIKE $3 ESCAPE '\' THEN 2
           ELSE 3
         END AS bucket
    FROM communities c
   WHERE lower(c.slug) = $1
      OR lower(c.name) LIKE $3 ESCAPE '\'
      OR lower(c.topic) LIKE $3 ESCAPE '\'
)
SELECT id, slug, name, topic, kind, member_count, accent_color, bucket
  FROM ranked WHERE %s
 ORDER BY bucket, member_count DESC, id
 LIMIT $%d`, keyset, len(args))

	rows, err := r.pool.Query(ctx, sql, args...)
	if err != nil {
		return domsearch.Page[domsearch.CommunityResult]{}, fmt.Errorf("searchrepo communities: %w", err)
	}
	defer rows.Close()

	var out []keyed[domsearch.CommunityResult]
	for rows.Next() {
		var it domsearch.CommunityResult
		var bucket int
		if err := rows.Scan(&it.ID, &it.Slug, &it.Name, &it.Topic, &it.Kind,
			&it.MemberCount, &it.AccentColor, &bucket); err != nil {
			return domsearch.Page[domsearch.CommunityResult]{}, err
		}
		out = append(out, keyed[domsearch.CommunityResult]{it, domsearch.Cursor{
			Cat: string(domsearch.CategoryCommunities), B: bucket,
			S1: strconv.Itoa(it.MemberCount), ID: it.ID.String(),
		}})
	}
	if err := rows.Err(); err != nil {
		return domsearch.Page[domsearch.CommunityResult]{}, err
	}
	return pageOut(out, limit), nil
}

// ---------------------------------------------------------------------------
// COMPETITIONS — active only ("active" is the authoritative flag, matching
// /competitions/highlights). bucket: 0 exact slug · 1 name/short prefix ·
// 2 contains. Tiebreak: featured DESC (real editorial flag), id ASC.
// ---------------------------------------------------------------------------

func (r *Repository) SearchCompetitions(
	ctx context.Context, q string, limit int, cur *domsearch.Cursor,
) (domsearch.Page[domsearch.CompetitionResult], error) {
	exact, prefix, contains := likePatterns(q)
	keyset, args := "TRUE", []any{exact, prefix, contains}
	if cur != nil {
		feat, err := strconv.Atoi(cur.S1) // 1|0
		if err != nil {
			return domsearch.Page[domsearch.CompetitionResult]{}, domsearch.ErrInvalidCursor
		}
		args = append(args, cur.B, feat == 1, cur.ID)
		keyset = `(bucket > $4 OR (bucket = $4 AND featured < $5)
		           OR (bucket = $4 AND featured = $5 AND id > $6::uuid))`
	}
	args = append(args, limit+1)
	sql := fmt.Sprintf(`
WITH ranked AS (
  SELECT c.id, c.slug, c.name, c.short_name, c.region, c.accent_color,
         c.featured, c.active,
         CASE
           WHEN lower(c.slug) = $1 THEN 0
           WHEN lower(c.name) LIKE $2 ESCAPE '\'
             OR lower(c.short_name) LIKE $2 ESCAPE '\' THEN 1
           ELSE 2
         END AS bucket
    FROM competitions c
   WHERE c.active = TRUE
     AND (lower(c.slug) = $1
       OR lower(c.name) LIKE $3 ESCAPE '\'
       OR lower(c.short_name) LIKE $3 ESCAPE '\')
)
SELECT id, slug, name, short_name, region, accent_color, featured, active, bucket
  FROM ranked WHERE %s
 ORDER BY bucket, featured DESC, id
 LIMIT $%d`, keyset, len(args))

	rows, err := r.pool.Query(ctx, sql, args...)
	if err != nil {
		return domsearch.Page[domsearch.CompetitionResult]{}, fmt.Errorf("searchrepo competitions: %w", err)
	}
	defer rows.Close()

	var out []keyed[domsearch.CompetitionResult]
	for rows.Next() {
		var it domsearch.CompetitionResult
		var bucket int
		if err := rows.Scan(&it.ID, &it.Slug, &it.Name, &it.ShortName, &it.Region,
			&it.AccentColor, &it.Featured, &it.Active, &bucket); err != nil {
			return domsearch.Page[domsearch.CompetitionResult]{}, err
		}
		feat := "0"
		if it.Featured {
			feat = "1"
		}
		out = append(out, keyed[domsearch.CompetitionResult]{it, domsearch.Cursor{
			Cat: string(domsearch.CategoryCompetitions), B: bucket,
			S1: feat, ID: it.ID.String(),
		}})
	}
	if err := rows.Err(); err != nil {
		return domsearch.Page[domsearch.CompetitionResult]{}, err
	}
	return pageOut(out, limit), nil
}

// ---------------------------------------------------------------------------
// MATCHES — team NAMES are match context (never Team identities). bucket:
// 0 = either team name prefix OR short-code exact · 1 = contains.
// Tiebreak: kickoff_ts DESC (recency), match_id ASC.
// ---------------------------------------------------------------------------

func (r *Repository) SearchMatches(
	ctx context.Context, q string, limit int, cur *domsearch.Cursor,
) (domsearch.Page[domsearch.MatchResult], error) {
	exact, prefix, contains := likePatterns(q)
	keyset, args := "TRUE", []any{exact, prefix, contains}
	if cur != nil {
		ts, err := time.Parse(time.RFC3339Nano, cur.S1)
		if err != nil {
			return domsearch.Page[domsearch.MatchResult]{}, domsearch.ErrInvalidCursor
		}
		args = append(args, cur.B, ts, cur.ID)
		keyset = `(bucket > $4 OR (bucket = $4 AND kickoff_ts < $5)
		           OR (bucket = $4 AND kickoff_ts = $5 AND match_id > $6::uuid))`
	}
	args = append(args, limit+1)
	sql := fmt.Sprintf(`
WITH ranked AS (
  SELECT m.match_id, m.competition_id, c.name AS competition_name,
         m.home_team_name, m.home_team_short, m.home_team_color,
         m.away_team_name, m.away_team_short, m.away_team_color,
         m.kickoff_ts, m.state, m.home_score, m.away_score,
         CASE
           WHEN lower(m.home_team_name) LIKE $2 ESCAPE '\'
             OR lower(m.away_team_name) LIKE $2 ESCAPE '\'
             OR lower(m.home_team_short) = $1
             OR lower(m.away_team_short) = $1 THEN 0
           ELSE 1
         END AS bucket
    FROM matches m
    JOIN competitions c ON c.id = m.competition_id
   WHERE lower(m.home_team_name) LIKE $3 ESCAPE '\'
      OR lower(m.away_team_name) LIKE $3 ESCAPE '\'
      OR lower(m.home_team_short) = $1
      OR lower(m.away_team_short) = $1
)
SELECT match_id, competition_id, competition_name,
       home_team_name, home_team_short, home_team_color,
       away_team_name, away_team_short, away_team_color,
       kickoff_ts, state, home_score, away_score, bucket
  FROM ranked WHERE %s
 ORDER BY bucket, kickoff_ts DESC, match_id
 LIMIT $%d`, keyset, len(args))

	rows, err := r.pool.Query(ctx, sql, args...)
	if err != nil {
		return domsearch.Page[domsearch.MatchResult]{}, fmt.Errorf("searchrepo matches: %w", err)
	}
	defer rows.Close()

	var out []keyed[domsearch.MatchResult]
	for rows.Next() {
		var it domsearch.MatchResult
		var bucket int
		if err := rows.Scan(&it.MatchID, &it.CompetitionID, &it.CompetitionName,
			&it.HomeTeamName, &it.HomeTeamShort, &it.HomeTeamColor,
			&it.AwayTeamName, &it.AwayTeamShort, &it.AwayTeamColor,
			&it.KickoffTs, &it.State, &it.HomeScore, &it.AwayScore, &bucket); err != nil {
			return domsearch.Page[domsearch.MatchResult]{}, err
		}
		out = append(out, keyed[domsearch.MatchResult]{it, domsearch.Cursor{
			Cat: string(domsearch.CategoryMatches), B: bucket,
			S1: encTime(it.KickoffTs), ID: it.MatchID.String(),
		}})
	}
	if err := rows.Err(); err != nil {
		return domsearch.Page[domsearch.MatchResult]{}, err
	}
	return pageOut(out, limit), nil
}

// ---------------------------------------------------------------------------
// POSTS — real Postgres FTS over the STORED tsvector ('simple' config, GIN).
// Only public + non-deleted posts. Sort: ts_rank DESC, created_at DESC, id ASC.
// Snippet via ts_headline (<b>…</b> markers). Author resolved like the feed
// (agent vs user join); user avatar versioned.
// ---------------------------------------------------------------------------

func (r *Repository) SearchPosts(
	ctx context.Context, q string, limit int, cur *domsearch.Cursor,
) (domsearch.Page[domsearch.PostResult], error) {
	keyset, args := "TRUE", []any{q}
	if cur != nil {
		rank, err1 := strconv.ParseFloat(cur.S1, 64)
		ts, err2 := time.Parse(time.RFC3339Nano, cur.S2)
		if err1 != nil || err2 != nil {
			return domsearch.Page[domsearch.PostResult]{}, domsearch.ErrInvalidCursor
		}
		args = append(args, rank, ts, cur.ID)
		keyset = `(rank < $2 OR (rank = $2 AND created_at < $3)
		           OR (rank = $2 AND created_at = $3 AND id > $4::uuid))`
	}
	args = append(args, limit+1)
	sql := fmt.Sprintf(`
WITH query AS (SELECT websearch_to_tsquery('simple', $1) AS tsq),
ranked AS (
  SELECT p.id, p.author_id, p.author_type, p.created_at,
         ts_rank(p.search_tsv, query.tsq)::float8 AS rank,
         ts_headline('simple', p.content, query.tsq,
           'StartSel=<b>,StopSel=</b>,MaxWords=30,MinWords=10') AS snippet,
         COALESCE(a.name, u.display_name, '') AS author_name,
         COALESCE(a.avatar, CASE
             WHEN u.avatar_url IS NOT NULL AND u.avatar_url <> '' AND u.avatar_updated_at IS NOT NULL
             THEN u.avatar_url || '?v=' || (extract(epoch FROM u.avatar_updated_at)::bigint)::text
             ELSE COALESCE(u.avatar_url, '') END, '') AS author_avatar,
         (SELECT COUNT(*) FROM post_likes l WHERE l.post_id = p.id) AS like_count,
         (SELECT COUNT(*) FROM comments cm WHERE cm.post_id = p.id) AS comment_count
    FROM posts p
    CROSS JOIN query
    LEFT JOIN agent_profiles a ON p.author_type = 'agent' AND a.id = p.author_id
    LEFT JOIN users u ON p.author_type <> 'agent' AND u.id = p.author_id
   WHERE p.search_tsv @@ query.tsq
     AND p.deleted_at IS NULL
     AND p.visibility = 'public'
)
SELECT id, author_id, author_type, created_at, rank, snippet,
       author_name, author_avatar, like_count, comment_count
  FROM ranked WHERE %s
 ORDER BY rank DESC, created_at DESC, id
 LIMIT $%d`, keyset, len(args))

	rows, err := r.pool.Query(ctx, sql, args...)
	if err != nil {
		return domsearch.Page[domsearch.PostResult]{}, fmt.Errorf("searchrepo posts: %w", err)
	}
	defer rows.Close()

	var out []keyed[domsearch.PostResult]
	for rows.Next() {
		var it domsearch.PostResult
		var rank float64
		if err := rows.Scan(&it.ID, &it.AuthorID, &it.AuthorType, &it.CreatedAt,
			&rank, &it.Snippet, &it.AuthorName, &it.AuthorAvatar,
			&it.LikeCount, &it.CommentCount); err != nil {
			return domsearch.Page[domsearch.PostResult]{}, err
		}
		out = append(out, keyed[domsearch.PostResult]{it, domsearch.Cursor{
			Cat: string(domsearch.CategoryPosts), B: 0,
			S1: encFloat(rank), S2: encTime(it.CreatedAt), ID: it.ID.String(),
		}})
	}
	if err := rows.Err(); err != nil {
		return domsearch.Page[domsearch.PostResult]{}, err
	}
	return pageOut(out, limit), nil
}

// ---------------------------------------------------------------------------
// SEARCH HISTORY — private per user. Dedupe by UNIQUE upsert (re-search
// refreshes recency); pruned to HistoryLimit on every write.
// ---------------------------------------------------------------------------

func (r *Repository) RecordHistory(ctx context.Context, userID uuid.UUID, normalizedQuery string) error {
	if _, err := r.pool.Exec(ctx, `
INSERT INTO search_history (user_id, query) VALUES ($1, $2)
ON CONFLICT (user_id, query) DO UPDATE SET created_at = NOW()`,
		userID, normalizedQuery); err != nil {
		return fmt.Errorf("searchrepo history insert: %w", err)
	}
	// Bound the per-user history (keep the HistoryLimit most recent).
	if _, err := r.pool.Exec(ctx, `
DELETE FROM search_history
 WHERE user_id = $1
   AND id NOT IN (
     SELECT id FROM search_history
      WHERE user_id = $1
      ORDER BY created_at DESC, id DESC
      LIMIT $2)`,
		userID, domsearch.HistoryLimit); err != nil {
		return fmt.Errorf("searchrepo history prune: %w", err)
	}
	return nil
}

func (r *Repository) History(ctx context.Context, userID uuid.UUID, limit int) ([]domsearch.HistoryEntry, error) {
	if limit <= 0 || limit > domsearch.HistoryLimit {
		limit = domsearch.HistoryLimit
	}
	rows, err := r.pool.Query(ctx, `
SELECT query, created_at FROM search_history
 WHERE user_id = $1
 ORDER BY created_at DESC, id DESC
 LIMIT $2`, userID, limit)
	if err != nil {
		return nil, fmt.Errorf("searchrepo history: %w", err)
	}
	defer rows.Close()
	entries := []domsearch.HistoryEntry{}
	for rows.Next() {
		var e domsearch.HistoryEntry
		if err := rows.Scan(&e.Query, &e.CreatedAt); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

func (r *Repository) ClearHistory(ctx context.Context, userID uuid.UUID) error {
	if _, err := r.pool.Exec(ctx,
		`DELETE FROM search_history WHERE user_id = $1`, userID); err != nil {
		return fmt.Errorf("searchrepo history clear: %w", err)
	}
	return nil
}
