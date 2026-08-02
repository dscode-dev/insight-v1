// Package interactions proxies the Saved Posts + Boost BFF endpoints to
// insight-social (AZTECA-SOCIAL-A). The Azteca mobile client talks to the
// Gateway only; insight-social owns the saved_posts + boosts entities and is
// the single source of truth. These handlers are thin authenticated
// pass-throughs: they take the user id from the verified token (never the
// request body) and forward it to social as the X-User-Id header.
package interactions

import (
	"context"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

// WriteGate reports whether a user may perform an additive participation
// mutation (boost/save). It returns a non-empty blockedCode ("account_banned" /
// "account_suspended") when the user is enforced out, or err on an internal
// check failure (fail-closed). Nil gate ⇒ no enforcement (CONSOLE-SOCIAL-B).
type WriteGate func(ctx context.Context, userID uuid.UUID) (blockedCode string, err error)

type Handler struct {
	socialBase string
	client     *http.Client
	gate       WriteGate
}

func New(socialHTTPBaseURL string) *Handler {
	return &Handler{
		socialBase: strings.TrimRight(socialHTTPBaseURL, "/"),
		client:     &http.Client{Timeout: 6 * time.Second},
	}
}

// WithWriteGate wires the moderation write-gate so banned/suspended users cannot
// boost/save (closes the SOCIAL-B enforcement gap).
func (h *Handler) WithWriteGate(g WriteGate) *Handler {
	h.gate = g
	return h
}

// Save / Unsave — POST|DELETE /v1/posts/{postId}/save.
func (h *Handler) Save(w http.ResponseWriter, r *http.Request)   { h.proxyPost(w, r, "/save") }
func (h *Handler) Unsave(w http.ResponseWriter, r *http.Request) { h.proxyPost(w, r, "/save") }

// Boost / Unboost — POST|DELETE /v1/posts/{postId}/boost. Forwards the request
// body (optional boost_type/weight) so future producers can extend it.
func (h *Handler) Boost(w http.ResponseWriter, r *http.Request)   { h.proxyPost(w, r, "/boost") }
func (h *Handler) Unboost(w http.ResponseWriter, r *http.Request) { h.proxyPost(w, r, "/boost") }

// proxyPost forwards a per-post mutation (save/boost) to social, preserving the
// HTTP method and (for POST) the body, and injecting the authenticated user.
func (h *Handler) proxyPost(w http.ResponseWriter, r *http.Request, suffix string) {
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated")
		return
	}
	if h.socialBase == "" {
		writeError(w, http.StatusServiceUnavailable, "social_http_not_configured")
		return
	}
	postID := chi.URLParam(r, "postId")
	if postID == "" {
		writeError(w, http.StatusBadRequest, "missing_post_id")
		return
	}
	// CONSOLE-SOCIAL-B: adding a boost/save is a participation mutation — gate
	// banned/suspended users. Removing (DELETE) stays allowed (reductive).
	if r.Method == http.MethodPost && h.gate != nil {
		code, gerr := h.gate(r.Context(), userID)
		if gerr != nil {
			writeError(w, http.StatusInternalServerError, "moderation_check_failed")
			return
		}
		if code != "" {
			writeError(w, http.StatusForbidden, code)
			return
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()

	var body io.Reader
	if r.Method == http.MethodPost {
		body = r.Body
	}
	upstream := h.socialBase + "/posts/" + postID + suffix
	req, err := http.NewRequestWithContext(ctx, r.Method, upstream, body)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "request_build_failed")
		return
	}
	req.Header.Set("X-User-Id", userID.String())
	req.Header.Set("Content-Type", "application/json; charset=utf-8")
	h.forward(w, req)
}

// SavedPosts — GET /v1/me/saved-posts. The caller's saved posts (newest first).
func (h *Handler) SavedPosts(w http.ResponseWriter, r *http.Request) {
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated")
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if h.socialBase == "" {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"saved_posts":[],"detail":"social_http_not_configured"}`))
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, h.socialBase+"/me/saved-posts", nil)
	if err != nil {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"saved_posts":[],"detail":"request_build_failed"}`))
		return
	}
	req.Header.Set("X-User-Id", userID.String())
	h.forward(w, req)
}

// SportsProfile — GET /v1/users/{userId}/sports-profile. Thin pass-through to
// social's enriched profile read (identity + grouped stats + versioned avatar).
// AZTECA-IDENTITY-B.
func (h *Handler) SportsProfile(w http.ResponseWriter, r *http.Request) {
	if _, ok := authmw.UserID(r.Context()); !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated")
		return
	}
	userID := chi.URLParam(r, "userId")
	if userID == "" {
		writeError(w, http.StatusBadRequest, "missing_user_id")
		return
	}
	if h.socialBase == "" {
		writeError(w, http.StatusServiceUnavailable, "social_http_not_configured")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		h.socialBase+"/users/"+userID+"/sports-profile", nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "request_build_failed")
		return
	}
	h.forward(w, req)
}

// UpdateMyProfile — PATCH /v1/users/me. AZTECA-PROFILE-B. Forwards the verified
// user (X-User-Id, never a client-supplied id) + the JSON body to Social's
// authenticated profile write. Social validates + persists (display_name only).
func (h *Handler) UpdateMyProfile(w http.ResponseWriter, r *http.Request) {
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated")
		return
	}
	if h.socialBase == "" {
		writeError(w, http.StatusServiceUnavailable, "social_http_not_configured")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPatch,
		h.socialBase+"/users/me/profile", r.Body)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "request_build_failed")
		return
	}
	req.Header.Set("X-User-Id", userID.String())
	req.Header.Set("Content-Type", "application/json; charset=utf-8")
	h.forward(w, req)
}

// InteractionStates — GET /v1/posts/interaction-states?ids=a,b,c. The feed
// uses this to hydrate persisted save/boost state after reload without talking
// to Social directly.
func (h *Handler) InteractionStates(w http.ResponseWriter, r *http.Request) {
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthenticated")
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if h.socialBase == "" {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"states":[],"detail":"social_http_not_configured"}`))
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, h.socialBase+"/posts/interaction-states?"+r.URL.RawQuery, nil)
	if err != nil {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"states":[],"detail":"request_build_failed"}`))
		return
	}
	req.Header.Set("X-User-Id", userID.String())
	h.forward(w, req)
}

// forward executes the upstream request and streams status + JSON body back.
func (h *Handler) forward(w http.ResponseWriter, req *http.Request) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	resp, err := h.client.Do(req)
	if err != nil {
		writeError(w, http.StatusBadGateway, "social_unreachable")
		return
	}
	defer resp.Body.Close()
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func writeError(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(`{"detail":"` + detail + `"}`))
}
