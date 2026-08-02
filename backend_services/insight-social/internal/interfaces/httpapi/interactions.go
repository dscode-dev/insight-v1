// AZTECA-SOCIAL-A — Saved Posts + Boosts HTTP endpoints on the social service.
//
// These live on the social HTTP port (alongside /competitions/highlights). The
// Gateway proxies them and forwards the authenticated user id as the
// `X-User-Id` header — the social service trusts that header because the port
// is internal (cluster-only), exactly like the competitions read path. Social
// is the source of truth for both entities; no ranking is computed here.
package httpapi

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

// userIDHeader extracts the Gateway-forwarded authenticated user id. Missing or
// malformed → false (the handler answers 400).
func userIDHeader(r *http.Request) (uuid.UUID, bool) {
	raw := r.Header.Get("X-User-Id")
	if raw == "" {
		return uuid.Nil, false
	}
	id, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, false
	}
	return id, true
}

// SavePost handles `POST /posts/{postId}/save` and `DELETE /posts/{postId}/save`.
// Idempotent: save = INSERT … ON CONFLICT DO NOTHING; unsave = DELETE. Always
// echoes the resulting saved state so the client can confirm its optimistic UI.
func SavePost(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		userID, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "missing_user"})
			return
		}
		postID, err := uuid.Parse(r.PathValue("postId"))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_post_id"})
			return
		}

		switch r.Method {
		case http.MethodPost:
			_, err = pool.Exec(r.Context(), `
INSERT INTO saved_posts (post_id, user_id)
VALUES ($1, $2)
ON CONFLICT (user_id, post_id) DO NOTHING`, postID, userID)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "save_failed"})
				return
			}
			writeJSON(w, http.StatusOK, map[string]any{"post_id": postID.String(), "saved": true})
		case http.MethodDelete:
			_, err = pool.Exec(r.Context(),
				`DELETE FROM saved_posts WHERE user_id = $1 AND post_id = $2`, userID, postID)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "unsave_failed"})
				return
			}
			writeJSON(w, http.StatusOK, map[string]any{"post_id": postID.String(), "saved": false})
		default:
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "method_not_allowed"})
		}
	}
}

// boostRequest is the optional POST body. V1 clients send nothing (manual,
// weight 1); the fields exist so future producers can specify a type/weight.
type boostRequest struct {
	BoostType string `json:"boost_type"`
	Weight    *int   `json:"weight"`
}

// BoostPost handles `POST /posts/{postId}/boost` and `DELETE …`. A boost is a
// first-class row. POST upserts an ACTIVE boost of the given type (default
// manual/weight 1); DELETE revokes the caller's manual boost. The response
// echoes the boosted state + the post's current active boost count so the
// client never computes ranking.
func BoostPost(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		userID, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "missing_user"})
			return
		}
		postID, err := uuid.Parse(r.PathValue("postId"))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_post_id"})
			return
		}

		switch r.Method {
		case http.MethodPost:
			req := boostRequest{BoostType: "manual"}
			if r.Body != nil {
				_ = json.NewDecoder(r.Body).Decode(&req) // optional body
			}
			// V1 only enables manual boosts from the client. Other types are
			// reserved for trusted backend producers, not this endpoint.
			boostType := "manual"
			if req.BoostType == "manual" || req.BoostType == "" {
				boostType = "manual"
			}
			weight := 1
			if req.Weight != nil && *req.Weight >= 0 {
				weight = *req.Weight
			}
			_, err = pool.Exec(r.Context(), `
INSERT INTO boosts (post_id, user_id, boost_type, weight, status)
VALUES ($1, $2, $3, $4, 'active')
ON CONFLICT (user_id, post_id, boost_type)
DO UPDATE SET status = 'active', weight = EXCLUDED.weight, expires_at = NULL`,
				postID, userID, boostType, weight)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "boost_failed"})
				return
			}
			writeJSON(w, http.StatusOK, boostStateResponse(r, pool, postID, true))
		case http.MethodDelete:
			_, err = pool.Exec(r.Context(), `
UPDATE boosts SET status = 'revoked'
WHERE user_id = $1 AND post_id = $2 AND boost_type = 'manual'`, userID, postID)
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "unboost_failed"})
				return
			}
			writeJSON(w, http.StatusOK, boostStateResponse(r, pool, postID, false))
		default:
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "method_not_allowed"})
		}
	}
}

// boostStateResponse returns {post_id, boosted, boost_count} where boost_count
// is the number of ACTIVE boosts on the post (all types).
func boostStateResponse(r *http.Request, pool *pgxpool.Pool, postID uuid.UUID, boosted bool) map[string]any {
	var count int
	_ = pool.QueryRow(r.Context(),
		`SELECT COUNT(*) FROM boosts WHERE post_id = $1 AND status = 'active'`, postID).Scan(&count)
	return map[string]any{"post_id": postID.String(), "boosted": boosted, "boost_count": count}
}

// savedPostEntry is one row of GET /me/saved-posts.
type savedPostEntry struct {
	PostID    string `json:"post_id"`
	SavedAt   string `json:"saved_at"`
	Content   string `json:"content"`
	AuthorID  string `json:"author_id"`
	CreatedAt string `json:"created_at"`
}

// interactionState is the backend-owned per-post interaction snapshot consumed
// by the mobile feed. It is intentionally additive to the existing save/boost
// mutation endpoints.
type interactionState struct {
	PostID     string `json:"post_id"`
	Saved      bool   `json:"saved"`
	Boosted    bool   `json:"boosted"`
	BoostCount int    `json:"boost_count"`
}

// InteractionStates handles `GET /posts/interaction-states?ids=a,b,c`.
// It lets the Gateway hydrate feed cards from the single source of truth after
// app restart: saved_by_me, boosted_by_me and the active boost count.
func InteractionStates(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "method_not_allowed"})
			return
		}
		userID, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "missing_user"})
			return
		}

		parts := strings.Split(r.URL.Query().Get("ids"), ",")
		ids := make([]uuid.UUID, 0, len(parts))
		for _, raw := range parts {
			raw = strings.TrimSpace(raw)
			if raw == "" {
				continue
			}
			id, err := uuid.Parse(raw)
			if err != nil {
				writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_post_id"})
				return
			}
			ids = append(ids, id)
			if len(ids) >= 100 {
				break
			}
		}
		if len(ids) == 0 {
			writeJSON(w, http.StatusOK, map[string]any{"states": []interactionState{}})
			return
		}

		rows, err := pool.Query(r.Context(), `
SELECT p.id,
       EXISTS (
         SELECT 1 FROM saved_posts sp
          WHERE sp.post_id = p.id AND sp.user_id = $2
       ) AS saved,
       EXISTS (
         SELECT 1 FROM boosts b
          WHERE b.post_id = p.id
            AND b.user_id = $2
            AND b.boost_type = 'manual'
            AND b.status = 'active'
       ) AS boosted,
       (
         SELECT COUNT(*) FROM boosts b
          WHERE b.post_id = p.id AND b.status = 'active'
       ) AS boost_count
  FROM posts p
 WHERE p.id = ANY($1)
   AND p.deleted_at IS NULL`, ids, userID)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "interaction_state_query_failed"})
			return
		}
		defer rows.Close()

		out := make([]interactionState, 0, len(ids))
		for rows.Next() {
			var (
				id    uuid.UUID
				state interactionState
			)
			if err := rows.Scan(&id, &state.Saved, &state.Boosted, &state.BoostCount); err != nil {
				continue
			}
			state.PostID = id.String()
			out = append(out, state)
		}
		writeJSON(w, http.StatusOK, map[string]any{"states": out})
	}
}

// SavedPosts handles `GET /me/saved-posts`: the caller's saved posts, newest
// save first, joined to the (non-deleted) post for a self-contained list.
func SavedPosts(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "method_not_allowed"})
			return
		}
		userID, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "missing_user"})
			return
		}
		rows, err := pool.Query(r.Context(), `
SELECT sp.post_id, sp.created_at, p.content, p.author_id, p.created_at
  FROM saved_posts sp
  JOIN posts p ON p.id = sp.post_id AND p.deleted_at IS NULL
 WHERE sp.user_id = $1
 ORDER BY sp.created_at DESC
 LIMIT 200`, userID)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "saved_query_failed"})
			return
		}
		defer rows.Close()

		out := make([]savedPostEntry, 0, 16)
		for rows.Next() {
			var (
				e                  savedPostEntry
				savedTs, createdTs time.Time
			)
			if err := rows.Scan(&e.PostID, &savedTs, &e.Content, &e.AuthorID, &createdTs); err != nil {
				continue
			}
			e.SavedAt = savedTs.UTC().Format(time.RFC3339)
			e.CreatedAt = createdTs.UTC().Format(time.RFC3339)
			out = append(out, e)
		}
		writeJSON(w, http.StatusOK, map[string]any{"saved_posts": out})
	}
}
