// Console Social investigation plane (CONSOLE-SOCIAL-A2). Privileged READ-ONLY
// projections: comments observatory, communities, entity-centric relationships,
// boosts, and an entity-scoped social timeline. Internal port (gateway-only),
// proxied under /v1/console/social/*. Reuses helpers from console_social.go.
// No mutation. author_type preserved. Individual savers never exposed.

package httpapi

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// author CASE fragments for comments (c.*). Mirrors authorLabel() which is p.*.
const commentAuthorJoins = `
LEFT JOIN users u           ON c.author_type='user'  AND u.id=c.author_id
LEFT JOIN agent_profiles ag ON c.author_type='agent' AND ag.id=c.author_id`

func commentAuthorLabel() string {
	return `CASE c.author_type WHEN 'user' THEN COALESCE(u.username,'') WHEN 'agent' THEN COALESCE(ag.slug,'') ELSE 'admin' END,
CASE c.author_type WHEN 'user' THEN COALESCE(u.display_name,'') WHEN 'agent' THEN COALESCE(ag.name,'') ELSE 'Admin' END,
CASE c.author_type WHEN 'user' THEN COALESCE(u.avatar_url,'') WHEN 'agent' THEN COALESCE(ag.avatar,'') ELSE '' END`
}

// ---- Comments Observatory ----

func ConsoleSocialComments(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		limit := clampLimit(q.Get("limit"))
		args := []any{}
		where := []string{"1=1"}
		if pid := q.Get("post_id"); isUUID(pid) {
			args = append(args, pid)
			where = append(where, "c.post_id=$"+strconv.Itoa(len(args)))
		}
		if aid := q.Get("author_id"); isUUID(aid) {
			args = append(args, aid)
			where = append(where, "c.author_id=$"+strconv.Itoa(len(args)))
		}
		if at := q.Get("author_type"); at == "user" || at == "agent" || at == "admin" {
			args = append(args, at)
			where = append(where, "c.author_type=$"+strconv.Itoa(len(args)))
		}
		if curTs, curID, ok := decodeCursor(q.Get("cursor")); ok {
			args = append(args, curTs, curID)
			where = append(where, "(c.created_at, c.id::text) < ($"+strconv.Itoa(len(args)-1)+"::timestamptz, $"+strconv.Itoa(len(args))+")")
		}
		args = append(args, limit+1)
		sql := `
SELECT c.id::text, c.post_id::text, COALESCE(c.parent_id::text,''), c.author_id::text, c.author_type, ` + commentAuthorLabel() + `,
 left(c.content,200), c.depth, c.created_at,
 (SELECT count(*) FROM comments rr WHERE rr.parent_id=c.id),
 COALESCE(left(p.content,80),'')
FROM comments c` + commentAuthorJoins + `
LEFT JOIN posts p ON p.id=c.post_id
WHERE ` + strings.Join(where, " AND ") + `
ORDER BY c.created_at DESC, c.id DESC LIMIT $` + strconv.Itoa(len(args))
		rows, err := pool.Query(r.Context(), sql, args...)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "comments_query_failed"})
			return
		}
		defer rows.Close()
		items := []map[string]any{}
		var lastTs time.Time
		var lastID string
		for rows.Next() {
			var id, pid, parent, aid, atype, uname, disp, avatar, content, postPrev string
			var depth int
			var created time.Time
			var replyN int64
			if rows.Scan(&id, &pid, &parent, &aid, &atype, &uname, &disp, &avatar, &content, &depth, &created, &replyN, &postPrev) != nil {
				continue
			}
			items = append(items, map[string]any{
				"id": id, "post_id": pid, "parent_id": parent, "author": authorObj(atype, aid, uname, disp, avatar),
				"author_type": atype, "content": content, "depth": depth, "reply_count": replyN,
				"post_preview": postPrev, "created_at": created.UTC().Format(time.RFC3339),
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

func ConsoleSocialComment(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !isUUID(id) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_id"})
			return
		}
		var cid, pid, parent, aid, atype, uname, disp, avatar, content string
		var depth int
		var created time.Time
		err := pool.QueryRow(r.Context(), `
SELECT c.id::text, c.post_id::text, COALESCE(c.parent_id::text,''), c.author_id::text, c.author_type, `+commentAuthorLabel()+`,
 c.content, c.depth, c.created_at
FROM comments c`+commentAuthorJoins+`
WHERE c.id=$1`, id).Scan(&cid, &pid, &parent, &aid, &atype, &uname, &disp, &avatar, &content, &depth, &created)
		if err != nil {
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "comment_not_found"})
			return
		}
		// Parent post summary (author resolved).
		var ppid, paid, patype, puname, pdisp, ppreview string
		_ = pool.QueryRow(r.Context(), `
SELECT p.id::text, p.author_id::text, p.author_type, `+authorLabel()+`, left(p.content,160)
FROM posts p`+authorJoins+` WHERE p.id=$1`, pid).Scan(&ppid, &paid, &patype, &puname, &pdisp, new(string), &ppreview)
		// Replies (this comment's children, depth 2).
		replies := commentChildren(r, pool, cid)
		var parentComment map[string]any
		if parent != "" {
			parentComment = commentSummary(r, pool, parent)
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"source": "insight-social",
			"comment": map[string]any{
				"id": cid, "post_id": pid, "parent_id": parent, "author": authorObj(atype, aid, uname, disp, avatar),
				"author_type": atype, "content": content, "depth": depth, "created_at": created.UTC().Format(time.RFC3339),
			},
			"parent_post":    map[string]any{"id": ppid, "author": authorObj(patype, paid, puname, pdisp, ""), "preview": ppreview},
			"parent_comment": parentComment,
			"replies":        replies,
		})
	}
}

func commentSummary(r *http.Request, pool *pgxpool.Pool, id string) map[string]any {
	var cid, aid, atype, uname, disp, content string
	var created time.Time
	if pool.QueryRow(r.Context(), `
SELECT c.id::text, c.author_id::text, c.author_type, `+commentAuthorLabel()+`, left(c.content,160), c.created_at
FROM comments c`+commentAuthorJoins+` WHERE c.id=$1`, id).Scan(&cid, &aid, &atype, &uname, &disp, new(string), &content, &created) != nil {
		return nil
	}
	return map[string]any{"id": cid, "author": authorObj(atype, aid, uname, disp, ""), "content": content, "created_at": created.UTC().Format(time.RFC3339)}
}

func commentChildren(r *http.Request, pool *pgxpool.Pool, parentID string) []map[string]any {
	rows, err := pool.Query(r.Context(), `
SELECT c.id::text, c.author_id::text, c.author_type, `+commentAuthorLabel()+`, c.content, c.depth, c.created_at
FROM comments c`+commentAuthorJoins+`
WHERE c.parent_id=$1 ORDER BY c.created_at ASC LIMIT 200`, parentID)
	out := []map[string]any{}
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var id, aid, atype, uname, disp, avatar, content string
		var depth int
		var created time.Time
		if rows.Scan(&id, &aid, &atype, &uname, &disp, &avatar, &content, &depth, &created) == nil {
			out = append(out, map[string]any{"id": id, "author": authorObj(atype, aid, uname, disp, avatar),
				"author_type": atype, "content": content, "depth": depth, "created_at": created.UTC().Format(time.RFC3339)})
		}
	}
	return out
}

// ---- Communities Observatory ----

func ConsoleSocialCommunities(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		limit := clampLimit(r.URL.Query().Get("limit"))
		rows, err := pool.Query(r.Context(), `
SELECT c.id::text, c.slug, c.name, c.topic, c.kind, c.member_count, c.active_now, c.created_at,
 (SELECT count(*) FROM community_members m WHERE m.community_id=c.id),
 (SELECT count(*) FROM community_members m WHERE m.community_id=c.id AND m.is_moderator)
FROM communities c ORDER BY c.member_count DESC, c.id DESC LIMIT $1`, limit)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "communities_query_failed"})
			return
		}
		defer rows.Close()
		items := []map[string]any{}
		for rows.Next() {
			var id, slug, name, topic, kind string
			var memberCount, activeNow int
			var created time.Time
			var actualMembers, mods int64
			if rows.Scan(&id, &slug, &name, &topic, &kind, &memberCount, &activeNow, &created, &actualMembers, &mods) == nil {
				items = append(items, map[string]any{"id": id, "slug": slug, "name": name, "topic": topic, "kind": kind,
					"member_count": actualMembers, "moderator_count": mods, "created_at": created.UTC().Format(time.RFC3339)})
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": "", "source": "insight-social"})
	}
}

func ConsoleSocialCommunity(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if !isUUID(id) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_id"})
			return
		}
		var cid, slug, name, topic, kind string
		var created time.Time
		var members, mods int64
		err := pool.QueryRow(r.Context(), `
SELECT c.id::text, c.slug, c.name, c.topic, c.kind, c.created_at,
 (SELECT count(*) FROM community_members m WHERE m.community_id=c.id),
 (SELECT count(*) FROM community_members m WHERE m.community_id=c.id AND m.is_moderator)
FROM communities c WHERE c.id=$1`, id).Scan(&cid, &slug, &name, &topic, &kind, &created, &members, &mods)
		if err != nil {
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "community_not_found"})
			return
		}
		recent := communityMembers(r, pool, id, false, 20)
		moderators := communityMembers(r, pool, id, true, 20)
		writeJSON(w, http.StatusOK, map[string]any{
			"source":         "insight-social",
			"identity":       map[string]any{"id": cid, "slug": slug, "name": name, "topic": topic, "kind": kind, "created_at": created.UTC().Format(time.RFC3339)},
			"membership":     map[string]any{"member_count": members, "moderator_count": mods},
			"recent_members": recent,
			"moderators":     moderators,
		})
	}
}

func communityMembers(r *http.Request, pool *pgxpool.Pool, communityID string, modsOnly bool, n int) []map[string]any {
	cond := ""
	if modsOnly {
		cond = " AND m.is_moderator"
	}
	rows, err := pool.Query(r.Context(), `
SELECT u.id::text, u.username, u.display_name, m.is_moderator, m.joined_at
FROM community_members m JOIN users u ON u.id=m.user_id
WHERE m.community_id=$1`+cond+`
ORDER BY m.joined_at DESC LIMIT $2`, communityID, n)
	out := []map[string]any{}
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var uid, uname, disp string
		var isMod bool
		var joined time.Time
		if rows.Scan(&uid, &uname, &disp, &isMod, &joined) == nil {
			out = append(out, map[string]any{"id": uid, "username": uname, "display_name": disp,
				"is_moderator": isMod, "joined_at": joined.UTC().Format(time.RFC3339)})
		}
	}
	return out
}

// ---- Relationship Explorer (entity-centric) ----

func ConsoleSocialRelationships(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		et, eid := q.Get("entity_type"), q.Get("entity_id")
		if (et != "user" && et != "agent") || !isUUID(eid) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_entity"})
			return
		}
		rels := []map[string]any{}
		// Followers (anyone following this entity). Target may be user or agent.
		rows, _ := pool.Query(r.Context(), `
SELECT r.actor_id::text, u.username, u.display_name, r.created_at
FROM relationships r JOIN users u ON u.id=r.actor_id
WHERE r.kind='follow' AND r.target_id=$1 ORDER BY r.created_at DESC LIMIT 100`, eid)
		for rows.Next() {
			var aid, uname, disp string
			var created time.Time
			if rows.Scan(&aid, &uname, &disp, &created) == nil {
				rels = append(rels, map[string]any{"type": "follow", "direction": "inbound",
					"target": map[string]any{"type": "user", "id": aid, "label": disp, "username": uname}, "created_at": created.UTC().Format(time.RFC3339)})
			}
		}
		rows.Close()
		if et == "user" {
			// Following (this user follows users/agents) — target polymorphic.
			rows2, _ := pool.Query(r.Context(), `
SELECT r.target_id::text, r.created_at,
 COALESCE(u.username, ag.slug, ''), COALESCE(u.display_name, ag.name, ''),
 CASE WHEN u.id IS NOT NULL THEN 'user' WHEN ag.id IS NOT NULL THEN 'agent' ELSE 'unknown' END
FROM relationships r
LEFT JOIN users u ON u.id=r.target_id
LEFT JOIN agent_profiles ag ON ag.id=r.target_id
WHERE r.kind='follow' AND r.actor_id=$1 ORDER BY r.created_at DESC LIMIT 100`, eid)
			for rows2.Next() {
				var tid, uname, disp, ttype string
				var created time.Time
				if rows2.Scan(&tid, &created, &uname, &disp, &ttype) == nil {
					rels = append(rels, map[string]any{"type": "follow", "direction": "outbound",
						"target": map[string]any{"type": ttype, "id": tid, "label": disp, "username": uname}, "created_at": created.UTC().Format(time.RFC3339)})
				}
			}
			rows2.Close()
			// Community memberships.
			rows3, _ := pool.Query(r.Context(), `
SELECT c.id::text, c.name, m.is_moderator, m.joined_at
FROM community_members m JOIN communities c ON c.id=m.community_id
WHERE m.user_id=$1 ORDER BY m.joined_at DESC LIMIT 100`, eid)
			for rows3.Next() {
				var cid, name string
				var isMod bool
				var joined time.Time
				if rows3.Scan(&cid, &name, &isMod, &joined) == nil {
					kind := "member_of"
					if isMod {
						kind = "moderates"
					}
					rels = append(rels, map[string]any{"type": kind, "direction": "outbound",
						"target": map[string]any{"type": "community", "id": cid, "label": name}, "created_at": joined.UTC().Format(time.RFC3339)})
				}
			}
			rows3.Close()
		}
		writeJSON(w, http.StatusOK, map[string]any{"entity": map[string]any{"type": et, "id": eid},
			"relationships": rels, "source": "insight-social"})
	}
}

// ---- Boost Observability ----

func ConsoleSocialBoosts(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		limit := clampLimit(q.Get("limit"))
		args := []any{}
		where := []string{"1=1"}
		if pid := q.Get("post_id"); isUUID(pid) {
			args = append(args, pid)
			where = append(where, "b.post_id=$"+strconv.Itoa(len(args)))
		}
		if uid := q.Get("user_id"); isUUID(uid) {
			args = append(args, uid)
			where = append(where, "b.user_id=$"+strconv.Itoa(len(args)))
		}
		if st := q.Get("status"); st == "active" || st == "expired" || st == "revoked" {
			args = append(args, st)
			where = append(where, "b.status=$"+strconv.Itoa(len(args)))
		}
		if curTs, curID, ok := decodeCursor(q.Get("cursor")); ok {
			args = append(args, curTs, curID)
			where = append(where, "(b.created_at, b.id::text) < ($"+strconv.Itoa(len(args)-1)+"::timestamptz, $"+strconv.Itoa(len(args))+")")
		}
		args = append(args, limit+1)
		sql := `
SELECT b.id::text, b.post_id::text, b.user_id::text, b.boost_type, b.weight, b.status,
 COALESCE(to_char(b.expires_at,'YYYY-MM-DD"T"HH24:MI:SSZ'),''), b.created_at, COALESCE(left(p.content,80),'')
FROM boosts b LEFT JOIN posts p ON p.id=b.post_id
WHERE ` + strings.Join(where, " AND ") + `
ORDER BY b.created_at DESC, b.id DESC LIMIT $` + strconv.Itoa(len(args))
		rows, err := pool.Query(r.Context(), sql, args...)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "boosts_query_failed"})
			return
		}
		defer rows.Close()
		items := []map[string]any{}
		var lastTs time.Time
		var lastID string
		for rows.Next() {
			var id, pid, uid, btype, status, expires, prev string
			var weight int
			var created time.Time
			if rows.Scan(&id, &pid, &uid, &btype, &weight, &status, &expires, &created, &prev) == nil {
				items = append(items, map[string]any{"id": id, "post_id": pid, "actor_user_id": uid, "boost_type": btype,
					"weight": weight, "status": status, "expires_at": expires, "created_at": created.UTC().Format(time.RFC3339),
					"post_preview": prev})
				lastTs, lastID = created, id
			}
		}
		next := ""
		if len(items) > limit {
			items = items[:limit]
			next = encodeCursor(lastTs, lastID)
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": next, "source": "insight-social"})
	}
}

// ---- Entity-scoped social timeline (DURABLE_ROW_PROJECTION) ----

func ConsoleSocialTimeline(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		et, eid := q.Get("entity_type"), q.Get("entity_id")
		if !isUUID(eid) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_entity"})
			return
		}
		limit := clampLimit(q.Get("limit"))
		var sql string
		switch et {
		case "user", "agent":
			sql = `
SELECT * FROM (
  SELECT 'post_created' k, p.id::text id, p.created_at at, p.id::text target_id, 'post' target_type FROM posts p WHERE p.author_id=$1 AND p.deleted_at IS NULL
  UNION ALL
  SELECT 'comment_created', c.id::text, c.created_at, c.post_id::text, 'post' FROM comments c WHERE c.author_id=$1
  UNION ALL
  SELECT 'follow_created', r.id::text, r.created_at, r.target_id::text, 'account' FROM relationships r WHERE r.actor_id=$1 AND r.kind='follow'
  UNION ALL
  SELECT 'boost_activated', b.id::text, b.created_at, b.post_id::text, 'post' FROM boosts b WHERE b.user_id=$1
) t ORDER BY t.at DESC LIMIT $2`
		case "post":
			sql = `
SELECT * FROM (
  SELECT 'post_created' k, p.id::text id, p.created_at at, p.id::text target_id, 'post' target_type FROM posts p WHERE p.id=$1
  UNION ALL
  SELECT 'comment_created', c.id::text, c.created_at, c.id::text, 'comment' FROM comments c WHERE c.post_id=$1
  UNION ALL
  SELECT 'boost_activated', b.id::text, b.created_at, b.id::text, 'boost' FROM boosts b WHERE b.post_id=$1
) t ORDER BY t.at DESC LIMIT $2`
		default:
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_entity_type"})
			return
		}
		rows, err := pool.Query(r.Context(), sql, eid, limit)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "timeline_query_failed"})
			return
		}
		defer rows.Close()
		items := []map[string]any{}
		for rows.Next() {
			var k, id, targetID, targetType string
			var at time.Time
			if rows.Scan(&k, &id, &at, &targetID, &targetType) == nil {
				items = append(items, map[string]any{"id": id, "kind": k, "at": at.UTC().Format(time.RFC3339),
					"target": map[string]any{"id": targetID, "type": targetType},
					"domain": "social", "provenance": "DURABLE_ROW_PROJECTION"})
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{"entity": map[string]any{"type": et, "id": eid},
			"items": items, "provenance": "DURABLE_ROW_PROJECTION", "source": "insight-social"})
	}
}
