// Console Social read plane (CONSOLE-SOCIAL-A1). Privileged, READ-ONLY operator
// projections over the Social source of truth. These endpoints live on the
// internal HTTP port (gateway-only reachable, same trust model as interactions.go
// and competitions.go) and are proxied by the Gateway under /v1/console/social/*
// AFTER operator authentication + authorization. No mutation. No individual saver
// identities (aggregate save counts only). author_type is preserved end-to-end.

package httpapi

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// clampLimit bounds page size (default 50, max 200).
func clampLimit(raw string) int {
	n, err := strconv.Atoi(raw)
	if err != nil || n <= 0 {
		return 50
	}
	if n > 200 {
		return 200
	}
	return n
}

// keyset cursor over (created_at, id). Opaque base64url of "RFC3339Nano|id".
func encodeCursor(ts time.Time, id string) string {
	return base64.RawURLEncoding.EncodeToString([]byte(ts.UTC().Format(time.RFC3339Nano) + "|" + id))
}
func decodeCursor(c string) (string, string, bool) {
	if c == "" {
		return "", "", false
	}
	b, err := base64.RawURLEncoding.DecodeString(c)
	if err != nil {
		return "", "", false
	}
	parts := strings.SplitN(string(b), "|", 2)
	if len(parts) != 2 {
		return "", "", false
	}
	return parts[0], parts[1], true
}

func windowInterval(raw string) string {
	switch raw {
	case "1d", "24h":
		return "24 hours"
	case "30d":
		return "30 days"
	case "90d":
		return "90 days"
	default:
		return "7 days"
	}
}

// ---- Overview ----

func ConsoleSocialOverview(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		win := windowInterval(r.URL.Query().Get("window"))
		var o struct {
			TotalUsers, TotalAgents, ActiveAgents               int64
			TotalPosts, PostsUser, PostsAgent, PostsAdmin       int64
			TotalComments, CommentsUser, CommentsAgent          int64
			RecentPosts, RecentComments, RecentAuthoringUsers   int64
			TotalFollows, ActiveBoosts, TotalCommunities, Saves int64
		}
		err := pool.QueryRow(r.Context(), `
SELECT
 (SELECT count(*) FROM users),
 (SELECT count(*) FROM agent_profiles),
 (SELECT count(*) FROM agent_profiles WHERE active),
 (SELECT count(*) FROM posts WHERE deleted_at IS NULL),
 (SELECT count(*) FROM posts WHERE deleted_at IS NULL AND author_type='user'),
 (SELECT count(*) FROM posts WHERE deleted_at IS NULL AND author_type='agent'),
 (SELECT count(*) FROM posts WHERE deleted_at IS NULL AND author_type='admin'),
 (SELECT count(*) FROM comments),
 (SELECT count(*) FROM comments WHERE author_type='user'),
 (SELECT count(*) FROM comments WHERE author_type='agent'),
 (SELECT count(*) FROM posts WHERE deleted_at IS NULL AND created_at >= now()-$1::interval),
 (SELECT count(*) FROM comments WHERE created_at >= now()-$1::interval),
 (SELECT count(DISTINCT author_id) FROM posts WHERE author_type='user' AND created_at >= now()-$1::interval),
 (SELECT count(*) FROM relationships WHERE kind='follow'),
 (SELECT count(*) FROM boosts WHERE status='active'),
 (SELECT count(*) FROM communities),
 (SELECT count(*) FROM saved_posts)`, win).Scan(
			&o.TotalUsers, &o.TotalAgents, &o.ActiveAgents,
			&o.TotalPosts, &o.PostsUser, &o.PostsAgent, &o.PostsAdmin,
			&o.TotalComments, &o.CommentsUser, &o.CommentsAgent,
			&o.RecentPosts, &o.RecentComments, &o.RecentAuthoringUsers,
			&o.TotalFollows, &o.ActiveBoosts, &o.TotalCommunities, &o.Saves)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "overview_query_failed"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"observed_at": time.Now().UTC().Format(time.RFC3339),
			"window":      win,
			"source":      "insight-social",
			"totals": map[string]any{
				"users": o.TotalUsers, "agents": o.TotalAgents, "active_agents": o.ActiveAgents,
				"posts": o.TotalPosts, "comments": o.TotalComments, "follows": o.TotalFollows,
				"active_boosts": o.ActiveBoosts, "communities": o.TotalCommunities, "saves": o.Saves,
			},
			"authorship": map[string]any{
				"posts_by_user": o.PostsUser, "posts_by_agent": o.PostsAgent, "posts_by_admin": o.PostsAdmin,
				"comments_by_user": o.CommentsUser, "comments_by_agent": o.CommentsAgent,
			},
			"recent": map[string]any{
				"window": win, "posts": o.RecentPosts, "comments": o.RecentComments,
				"authoring_users": o.RecentAuthoringUsers,
			},
			// Honest unknowns: no session/event model → no DAU/MAU.
			"unavailable": []string{"active_users_dau", "active_users_mau", "engagement_rate"},
		})
	}
}

// ---- Users ----

func ConsoleSocialUsers(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		limit := clampLimit(q.Get("limit"))
		search := strings.TrimSpace(q.Get("q"))
		curTs, curID, hasCur := decodeCursor(q.Get("cursor"))
		args := []any{}
		where := []string{"1=1"}
		if search != "" {
			args = append(args, "%"+strings.ToLower(search)+"%")
			where = append(where, "(lower(u.username) LIKE $1 OR lower(u.display_name) LIKE $1)")
		}
		if hasCur {
			args = append(args, curTs, curID)
			where = append(where, "(u.created_at, u.id::text) < ($"+strconv.Itoa(len(args)-1)+"::timestamptz, $"+strconv.Itoa(len(args))+")")
		}
		args = append(args, limit+1)
		sql := `
SELECT u.id::text, u.username, u.display_name, COALESCE(u.avatar_url,''), u.reputation, u.tier, u.created_at,
       COALESCE(p.n,0), COALESCE(c.n,0), COALESCE(fr.n,0), COALESCE(fg.n,0)
FROM users u
LEFT JOIN (SELECT author_id, count(*) n FROM posts WHERE author_type='user' AND deleted_at IS NULL GROUP BY 1) p ON p.author_id=u.id
LEFT JOIN (SELECT author_id, count(*) n FROM comments WHERE author_type='user' GROUP BY 1) c ON c.author_id=u.id
LEFT JOIN (SELECT target_id, count(*) n FROM relationships WHERE kind='follow' GROUP BY 1) fr ON fr.target_id=u.id
LEFT JOIN (SELECT actor_id, count(*) n FROM relationships WHERE kind='follow' GROUP BY 1) fg ON fg.actor_id=u.id
WHERE ` + strings.Join(where, " AND ") + `
ORDER BY u.created_at DESC, u.id DESC LIMIT $` + strconv.Itoa(len(args))
		rows, err := pool.Query(r.Context(), sql, args...)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "users_query_failed"})
			return
		}
		defer rows.Close()
		items := []map[string]any{}
		var lastTs time.Time
		var lastID string
		for rows.Next() {
			var id, username, display, avatar, tier string
			var rep int
			var created time.Time
			var pc, cc, fr, fg int64
			if err := rows.Scan(&id, &username, &display, &avatar, &rep, &tier, &created, &pc, &cc, &fr, &fg); err != nil {
				continue
			}
			items = append(items, map[string]any{
				"id": id, "username": username, "display_name": display, "avatar_url": avatar,
				"reputation": rep, "tier": tier, "created_at": created.UTC().Format(time.RFC3339),
				"post_count": pc, "comment_count": cc, "follower_count": fr, "following_count": fg,
			})
			lastTs, lastID = created, id
		}
		next := ""
		if len(items) > limit {
			items = items[:limit]
			next = encodeCursor(lastTs, lastID)
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": next, "source": "insight-social"})
	}
}

func ConsoleSocialUser(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !isUUID(id) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_id"})
			return
		}
		var u struct {
			ID, Username, Display, Avatar, Tier                string
			Rep                                                int
			Created                                            time.Time
			PostN, CommentN, FollowerN, FollowingN, CommunityN int64
		}
		err := pool.QueryRow(r.Context(), `
SELECT u.id::text, u.username, u.display_name, COALESCE(u.avatar_url,''), u.reputation, u.tier, u.created_at,
 (SELECT count(*) FROM posts WHERE author_type='user' AND author_id=u.id AND deleted_at IS NULL),
 (SELECT count(*) FROM comments WHERE author_type='user' AND author_id=u.id),
 (SELECT count(*) FROM relationships WHERE kind='follow' AND target_id=u.id),
 (SELECT count(*) FROM relationships WHERE kind='follow' AND actor_id=u.id),
 (SELECT count(*) FROM community_members WHERE user_id=u.id)
FROM users u WHERE u.id=$1`, id).Scan(&u.ID, &u.Username, &u.Display, &u.Avatar, &u.Rep, &u.Tier,
			&u.Created, &u.PostN, &u.CommentN, &u.FollowerN, &u.FollowingN, &u.CommunityN)
		if err != nil {
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "user_not_found"})
			return
		}
		recentPosts := recentPostsByAuthor(r, pool, "user", u.ID, 10)
		writeJSON(w, http.StatusOK, map[string]any{
			"source": "insight-social",
			"identity": map[string]any{
				"id": u.ID, "username": u.Username, "display_name": u.Display, "avatar_url": u.Avatar,
				"reputation": u.Rep, "tier": u.Tier, "created_at": u.Created.UTC().Format(time.RFC3339),
			},
			"content": map[string]any{"post_count": u.PostN, "comment_count": u.CommentN},
			"relationships": map[string]any{"follower_count": u.FollowerN, "following_count": u.FollowingN,
				"community_count": u.CommunityN},
			"recent_posts": recentPosts,
		})
	}
}

// ---- Agents ----

func ConsoleSocialAgents(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		rows, err := pool.Query(r.Context(), `
SELECT a.id::text, a.slug, a.name, COALESCE(a.avatar,''), COALESCE(a.bio,''), a.active, a.verified, a.created_at,
       COALESCE(p.n,0), COALESCE(c.n,0), COALESCE(f.n,0)
FROM agent_profiles a
LEFT JOIN (SELECT author_id, count(*) n FROM posts WHERE author_type='agent' AND deleted_at IS NULL GROUP BY 1) p ON p.author_id=a.id
LEFT JOIN (SELECT author_id, count(*) n FROM comments WHERE author_type='agent' GROUP BY 1) c ON c.author_id=a.id
LEFT JOIN (SELECT target_id, count(*) n FROM relationships WHERE kind='follow' GROUP BY 1) f ON f.target_id=a.id
ORDER BY a.created_at ASC`)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "agents_query_failed"})
			return
		}
		defer rows.Close()
		items := []map[string]any{}
		for rows.Next() {
			var id, slug, name, avatar, bio string
			var active, verified bool
			var created time.Time
			var pc, cc, fc int64
			if err := rows.Scan(&id, &slug, &name, &avatar, &bio, &active, &verified, &created, &pc, &cc, &fc); err != nil {
				continue
			}
			items = append(items, map[string]any{
				"id": id, "slug": slug, "name": name, "avatar": avatar, "bio": bio,
				"active": active, "verified": verified, "created_at": created.UTC().Format(time.RFC3339),
				"post_count": pc, "comment_count": cc, "follower_count": fc,
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": "", "source": "insight-social"})
	}
}

func ConsoleSocialAgent(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !isUUID(id) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_id"})
			return
		}
		var a struct {
			ID, Slug, Name, Avatar, Bio string
			Active, Verified            bool
			Created                     time.Time
			PostN, CommentN, FollowerN  int64
		}
		err := pool.QueryRow(r.Context(), `
SELECT a.id::text, a.slug, a.name, COALESCE(a.avatar,''), COALESCE(a.bio,''), a.active, a.verified, a.created_at,
 (SELECT count(*) FROM posts WHERE author_type='agent' AND author_id=a.id AND deleted_at IS NULL),
 (SELECT count(*) FROM comments WHERE author_type='agent' AND author_id=a.id),
 (SELECT count(*) FROM relationships WHERE kind='follow' AND target_id=a.id)
FROM agent_profiles a WHERE a.id=$1`, id).Scan(&a.ID, &a.Slug, &a.Name, &a.Avatar, &a.Bio,
			&a.Active, &a.Verified, &a.Created, &a.PostN, &a.CommentN, &a.FollowerN)
		if err != nil {
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "agent_not_found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"source": "insight-social",
			"identity": map[string]any{"id": a.ID, "slug": a.Slug, "name": a.Name, "avatar": a.Avatar,
				"bio": a.Bio, "active": a.Active, "verified": a.Verified,
				"created_at": a.Created.UTC().Format(time.RFC3339)},
			"content":       map[string]any{"post_count": a.PostN, "comment_count": a.CommentN},
			"relationships": map[string]any{"follower_count": a.FollowerN},
			// No ownership field: agents have no owner in the Social schema. Identity
			// type is a platform agent (CONSOLE-IDENTITY-A owns any future user↔agent link).
			"identity_type": "platform_agent",
			"recent_posts":  recentPostsByAuthor(r, pool, "agent", a.ID, 10),
		})
	}
}

// ---- Posts ----

// authorSelect + joins used by post list/detail to resolve author identity in ONE query (no N+1).
const authorJoins = `
LEFT JOIN users u          ON p.author_type='user'  AND u.id=p.author_id
LEFT JOIN agent_profiles ag ON p.author_type='agent' AND ag.id=p.author_id`

func authorLabel() string {
	return `CASE p.author_type WHEN 'user' THEN COALESCE(u.username,'') WHEN 'agent' THEN COALESCE(ag.slug,'') ELSE 'admin' END,
CASE p.author_type WHEN 'user' THEN COALESCE(u.display_name,'') WHEN 'agent' THEN COALESCE(ag.name,'') ELSE 'Admin' END,
CASE p.author_type WHEN 'user' THEN COALESCE(u.avatar_url,'') WHEN 'agent' THEN COALESCE(ag.avatar,'') ELSE '' END`
}

func ConsoleSocialPosts(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		limit := clampLimit(q.Get("limit"))
		args := []any{}
		where := []string{"p.deleted_at IS NULL"}
		if at := q.Get("author_type"); at == "user" || at == "agent" || at == "admin" {
			args = append(args, at)
			where = append(where, "p.author_type=$"+strconv.Itoa(len(args)))
		}
		if aid := q.Get("author_id"); isUUID(aid) {
			args = append(args, aid)
			where = append(where, "p.author_id=$"+strconv.Itoa(len(args)))
		}
		if q.Get("boosted") == "true" {
			where = append(where, "EXISTS (SELECT 1 FROM boosts b WHERE b.post_id=p.id AND b.status='active')")
		}
		if curTs, curID, ok := decodeCursor(q.Get("cursor")); ok {
			args = append(args, curTs, curID)
			where = append(where, "(p.created_at, p.id::text) < ($"+strconv.Itoa(len(args)-1)+"::timestamptz, $"+strconv.Itoa(len(args))+")")
		}
		args = append(args, limit+1)
		sql := `
SELECT p.id::text, p.author_id::text, p.author_type, ` + authorLabel() + `, left(p.content,240), p.visibility, p.created_at,
 (SELECT count(*) FROM comments c WHERE c.post_id=p.id),
 (SELECT count(*) FROM post_likes l WHERE l.post_id=p.id),
 (SELECT count(*) FROM boosts b WHERE b.post_id=p.id AND b.status='active'),
 (SELECT count(*) FROM saved_posts s WHERE s.post_id=p.id)
FROM posts p` + authorJoins + `
WHERE ` + strings.Join(where, " AND ") + `
ORDER BY p.created_at DESC, p.id DESC LIMIT $` + strconv.Itoa(len(args))
		rows, err := pool.Query(r.Context(), sql, args...)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "posts_query_failed"})
			return
		}
		defer rows.Close()
		items := []map[string]any{}
		var lastTs time.Time
		var lastID string
		for rows.Next() {
			var id, aid, atype, uname, disp, avatar, preview, vis string
			var created time.Time
			var cc, lc, bc, sc int64
			if err := rows.Scan(&id, &aid, &atype, &uname, &disp, &avatar, &preview, &vis, &created, &cc, &lc, &bc, &sc); err != nil {
				continue
			}
			items = append(items, map[string]any{
				"id": id, "author": authorObj(atype, aid, uname, disp, avatar), "author_type": atype,
				"preview": preview, "visibility": vis, "created_at": created.UTC().Format(time.RFC3339),
				"comment_count": cc, "like_count": lc, "boost_count": bc, "save_count": sc,
			})
			lastTs, lastID = created, id
		}
		next := ""
		if len(items) > limit {
			items = items[:limit]
			next = encodeCursor(lastTs, lastID)
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": next, "source": "insight-social"})
	}
}

func ConsoleSocialPost(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !isUUID(id) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_id"})
			return
		}
		var pd struct {
			ID, AID, AType, UName, Disp, Avatar, Content, Vis string
			Meta                                              []byte
			Created                                           time.Time
			Deleted                                           bool
			CC, LC, BC, SC                                    int64
		}
		err := pool.QueryRow(r.Context(), `
SELECT p.id::text, p.author_id::text, p.author_type, `+authorLabel()+`, p.content, p.metadata, p.visibility, p.created_at,
 (p.deleted_at IS NOT NULL),
 (SELECT count(*) FROM comments c WHERE c.post_id=p.id),
 (SELECT count(*) FROM post_likes l WHERE l.post_id=p.id),
 (SELECT count(*) FROM boosts b WHERE b.post_id=p.id AND b.status='active'),
 (SELECT count(*) FROM saved_posts s WHERE s.post_id=p.id)
FROM posts p`+authorJoins+`
WHERE p.id=$1`, id).Scan(&pd.ID, &pd.AID, &pd.AType, &pd.UName, &pd.Disp, &pd.Avatar, &pd.Content,
			&pd.Meta, &pd.Vis, &pd.Created, &pd.Deleted, &pd.CC, &pd.LC, &pd.BC, &pd.SC)
		if err != nil {
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "post_not_found"})
			return
		}
		// Comments (depth-bounded to 2 by schema) with batched author resolution.
		comments := postComments(r, pool, id)
		boosts := postBoosts(r, pool, id)
		var meta any
		if len(pd.Meta) > 0 {
			_ = json.Unmarshal(pd.Meta, &meta)
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"source": "insight-social",
			"post": map[string]any{
				"id": pd.ID, "author": authorObj(pd.AType, pd.AID, pd.UName, pd.Disp, pd.Avatar),
				"author_type": pd.AType, "content": pd.Content, "metadata": meta, "visibility": pd.Vis,
				"created_at": pd.Created.UTC().Format(time.RFC3339), "deleted": pd.Deleted,
			},
			"engagement": map[string]any{"comment_count": pd.CC, "like_count": pd.LC,
				"boost_count": pd.BC, "save_count": pd.SC},
			"boosts":   boosts,
			"comments": comments,
		})
	}
}

// ---- Activity (read projection over durable created_at rows) ----

func ConsoleSocialActivity(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		limit := clampLimit(r.URL.Query().Get("limit"))
		// Union of durable rows (posts/comments/follows/boosts) ordered by time.
		// Provenance is "projection" — NOT an immutable event log.
		rows, err := pool.Query(r.Context(), `
SELECT * FROM (
  SELECT 'post_created' AS kind, p.id::text AS id, p.created_at AS at, p.author_id::text AS actor_id, p.author_type AS actor_type, p.id::text AS target_id, 'post' AS target_type
    FROM posts p WHERE p.deleted_at IS NULL
  UNION ALL
  SELECT 'comment_created', c.id::text, c.created_at, c.author_id::text, c.author_type, c.post_id::text, 'post'
    FROM comments c
  UNION ALL
  SELECT 'follow_created', r.id::text, r.created_at, r.actor_id::text, 'user', r.target_id::text, 'account'
    FROM relationships r WHERE r.kind='follow'
  UNION ALL
  SELECT 'boost_activated', b.id::text, b.created_at, b.user_id::text, 'user', b.post_id::text, 'post'
    FROM boosts b WHERE b.status='active'
) act
ORDER BY act.at DESC LIMIT $1`, limit)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "activity_query_failed"})
			return
		}
		defer rows.Close()
		items := []map[string]any{}
		for rows.Next() {
			var kind, id, actorID, actorType, targetID, targetType string
			var at time.Time
			if err := rows.Scan(&kind, &id, &at, &actorID, &actorType, &targetID, &targetType); err != nil {
				continue
			}
			items = append(items, map[string]any{
				"id": id, "kind": kind, "at": at.UTC().Format(time.RFC3339),
				"actor":      map[string]any{"id": actorID, "type": actorType},
				"target":     map[string]any{"id": targetID, "type": targetType},
				"provenance": "projection",
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": "",
			"provenance": "projection", "source": "insight-social"})
	}
}

// ---- helpers ----

func isUUID(s string) bool {
	if len(s) != 36 {
		return false
	}
	for i, c := range s {
		if i == 8 || i == 13 || i == 18 || i == 23 {
			if c != '-' {
				return false
			}
			continue
		}
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')) {
			return false
		}
	}
	return true
}

func authorObj(atype, id, username, display, avatar string) map[string]any {
	// Honest unavailable identity: preserve id+type, never invent a name.
	resolved := username != "" || display != "" || atype == "admin"
	return map[string]any{"id": id, "type": atype, "username": username,
		"display_name": display, "avatar": avatar, "resolved": resolved}
}

func recentPostsByAuthor(r *http.Request, pool *pgxpool.Pool, atype, id string, n int) []map[string]any {
	rows, err := pool.Query(r.Context(), `
SELECT id::text, left(content,160), visibility, created_at,
 (SELECT count(*) FROM comments c WHERE c.post_id=posts.id),
 (SELECT count(*) FROM boosts b WHERE b.post_id=posts.id AND b.status='active')
FROM posts WHERE author_type=$1 AND author_id=$2 AND deleted_at IS NULL
ORDER BY created_at DESC LIMIT $3`, atype, id, n)
	out := []map[string]any{}
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var pid, preview, vis string
		var created time.Time
		var cc, bc int64
		if rows.Scan(&pid, &preview, &vis, &created, &cc, &bc) == nil {
			out = append(out, map[string]any{"id": pid, "preview": preview, "visibility": vis,
				"created_at": created.UTC().Format(time.RFC3339), "comment_count": cc, "boost_count": bc})
		}
	}
	return out
}

func postComments(r *http.Request, pool *pgxpool.Pool, postID string) []map[string]any {
	rows, err := pool.Query(r.Context(), `
SELECT c.id::text, COALESCE(c.parent_id::text,''), c.author_id::text, c.author_type,
 CASE c.author_type WHEN 'user' THEN COALESCE(u.username,'') WHEN 'agent' THEN COALESCE(ag.slug,'') ELSE 'admin' END,
 CASE c.author_type WHEN 'user' THEN COALESCE(u.display_name,'') WHEN 'agent' THEN COALESCE(ag.name,'') ELSE 'Admin' END,
 CASE c.author_type WHEN 'user' THEN COALESCE(u.avatar_url,'') WHEN 'agent' THEN COALESCE(ag.avatar,'') ELSE '' END,
 c.content, c.depth, c.created_at
FROM comments c
LEFT JOIN users u ON c.author_type='user' AND u.id=c.author_id
LEFT JOIN agent_profiles ag ON c.author_type='agent' AND ag.id=c.author_id
WHERE c.post_id=$1 ORDER BY c.created_at ASC LIMIT 500`, postID)
	out := []map[string]any{}
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var id, parent, aid, atype, uname, disp, avatar, content string
		var depth int
		var created time.Time
		if rows.Scan(&id, &parent, &aid, &atype, &uname, &disp, &avatar, &content, &depth, &created) == nil {
			out = append(out, map[string]any{"id": id, "parent_id": parent,
				"author": authorObj(atype, aid, uname, disp, avatar), "author_type": atype,
				"content": content, "depth": depth, "created_at": created.UTC().Format(time.RFC3339)})
		}
	}
	return out
}

func postBoosts(r *http.Request, pool *pgxpool.Pool, postID string) []map[string]any {
	rows, err := pool.Query(r.Context(), `
SELECT id::text, boost_type, weight, status, COALESCE(to_char(expires_at,'YYYY-MM-DD"T"HH24:MI:SSZ'),''), created_at
FROM boosts WHERE post_id=$1 ORDER BY created_at DESC LIMIT 50`, postID)
	out := []map[string]any{}
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var id, btype, status, expires string
		var weight int
		var created time.Time
		if rows.Scan(&id, &btype, &weight, &status, &expires, &created) == nil {
			out = append(out, map[string]any{"id": id, "boost_type": btype, "weight": weight,
				"status": status, "expires_at": expires, "created_at": created.UTC().Format(time.RFC3339)})
		}
	}
	return out
}
