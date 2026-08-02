// FEATURE-NOTIFICATIONS-V1 Stage 2 — HTTP handlers (Notification Orchestrator).
//
// Endpoint matrix (all requireAuth; the viewer is the VERIFIED session identity
// from authmw, never client-supplied):
//
//   GET   /v1/notifications                 → ListResponse (cursor + has_more + unread_count)
//   GET   /v1/notifications/unread-count     → UnreadCountResponse (cached a few seconds)
//   PATCH /v1/notifications/{id}/read        → MarkReadResponse (updated notif + unread_count)
//   PATCH /v1/notifications/read-all         → MarkAllReadResponse (marked + unread_count)
package notificationbff

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

const (
	defaultUpstreamTimeout = 4 * time.Second
	listPageCap            = 30
)

type Handlers struct {
	agg     *Aggregator
	social  SocialGateway
	cache   *UnreadCache
	metrics *Metrics
	timeout time.Duration
}

func NewHandlers(social SocialGateway, agg *Aggregator, cache *UnreadCache, m *Metrics) *Handlers {
	return &Handlers{agg: agg, social: social, cache: cache, metrics: m, timeout: defaultUpstreamTimeout}
}

// GET /v1/notifications
func (h *Handlers) List(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	h.metrics.request("list")
	defer func() { h.metrics.latency.WithLabelValues("list").Observe(time.Since(start).Seconds()) }()

	viewer, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "")
		return
	}
	cursor := r.URL.Query().Get("cursor")
	unreadOnly := r.URL.Query().Get("unread_only") == "true"
	limit := listPageCap
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= listPageCap {
			limit = n
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()

	// Unread cache: a hit skips the unread fan-out. Only the FIRST page
	// (no cursor, not unread-only) reflects the badge; deeper pages don't
	// re-fetch the count.
	cachedUnread := int64(-1)
	if cursor == "" && !unreadOnly {
		if c, hit := h.cache.Get(viewer.String()); hit {
			h.metrics.cacheHit()
			cachedUnread = c
		} else {
			h.metrics.cacheMiss()
		}
	}
	store := func(n int64) { h.cache.Set(viewer.String(), n) }

	resp, err := h.agg.List(ctx, viewer.String(), cursor, limit, unreadOnly, cachedUnread, store)
	if err != nil {
		h.writeUpstream(w, "list", err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// GET /v1/notifications/unread-count
func (h *Handlers) UnreadCount(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	h.metrics.request("unread_count")
	defer func() { h.metrics.latency.WithLabelValues("unread_count").Observe(time.Since(start).Seconds()) }()

	viewer, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "")
		return
	}
	if c, hit := h.cache.Get(viewer.String()); hit {
		h.metrics.cacheHit()
		writeJSON(w, http.StatusOK, UnreadCountResponse{UnreadCount: c})
		return
	}
	h.metrics.cacheMiss()

	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()
	n, err := h.social.UnreadCount(ctx, viewer.String())
	if err != nil {
		h.writeUpstream(w, "unread_count", err)
		return
	}
	h.cache.Set(viewer.String(), n)
	writeJSON(w, http.StatusOK, UnreadCountResponse{UnreadCount: n})
}

// PATCH /v1/notifications/{id}/read
func (h *Handlers) MarkRead(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	h.metrics.request("mark_read")
	defer func() { h.metrics.latency.WithLabelValues("mark_read").Observe(time.Since(start).Seconds()) }()

	viewer, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "")
		return
	}
	id := chi.URLParam(r, "id")
	if id == "" {
		writeErr(w, http.StatusBadRequest, "missing_id", "")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()
	res, err := h.social.MarkRead(ctx, viewer.String(), id)
	if err != nil {
		h.writeUpstream(w, "mark_read", err)
		return
	}
	// A mutation happened → the cached count is stale. Store the authoritative
	// value so the badge is never inconsistent.
	h.cache.Set(viewer.String(), res.UnreadCount)

	out := MarkReadResponse{Changed: res.Changed, UnreadCount: res.UnreadCount}
	// Return the updated notification (no second call). Fetched by reading the
	// first page and finding it is wasteful; instead the client already holds
	// the row and flips read locally — but to honor "return updated notif" we
	// surface it when the upstream provided it. Social's MarkRead returns only
	// changed+count, so we synthesize the minimal read patch the client needs.
	if res.Changed {
		out.Notification = &Notification{ID: id, Read: true, Capabilities: NotificationCaps{CanMarkRead: false}}
	}
	writeJSON(w, http.StatusOK, out)
}

// PATCH /v1/notifications/read-all
func (h *Handlers) MarkAllRead(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	h.metrics.request("mark_all_read")
	defer func() { h.metrics.latency.WithLabelValues("mark_all_read").Observe(time.Since(start).Seconds()) }()

	viewer, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()
	res, err := h.social.MarkAllRead(ctx, viewer.String())
	if err != nil {
		h.writeUpstream(w, "mark_all_read", err)
		return
	}
	h.cache.Set(viewer.String(), res.UnreadCount) // authoritative (0 after mark-all)
	writeJSON(w, http.StatusOK, MarkAllReadResponse{Marked: res.Marked, UnreadCount: res.UnreadCount})
}

// ---- upstream error mapping (gRPC → HTTP) ----

func (h *Handlers) writeUpstream(w http.ResponseWriter, endpoint string, err error) {
	s, _ := status.FromError(err)
	switch s.Code() {
	case codes.NotFound:
		writeErr(w, http.StatusNotFound, "notification_not_found", "")
	case codes.InvalidArgument:
		writeErr(w, http.StatusBadRequest, "invalid_request", s.Message())
	case codes.DeadlineExceeded:
		h.metrics.timeout(endpoint)
		writeErr(w, http.StatusGatewayTimeout, "notification_upstream_timeout", "")
	case codes.Canceled:
		writeErr(w, 499, "client_closed_request", "")
	default:
		writeErr(w, http.StatusBadGateway, "notification_upstream_error", "")
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, status int, code, detail string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	body := map[string]string{"error": code}
	if detail != "" {
		body["detail"] = detail
	}
	_ = json.NewEncoder(w).Encode(body)
}
