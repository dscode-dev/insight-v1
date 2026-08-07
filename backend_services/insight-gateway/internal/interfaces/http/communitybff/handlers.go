// FEATURE-COMMUNITIES-V1 Stage 2 — HTTP handlers (Community Orchestrator).
//
// Endpoint matrix (all requireAuth; the viewer id is the VERIFIED session
// identity from authmw, never client-supplied):
//
//   GET    /v1/hub/communities/{id}              → Detail (aggregate)
//   GET    /v1/hub/communities/{id}/members      → MembersPage (cursor, ?role=)
//   GET    /v1/hub/communities/{id}/discussions  → DiscussionsPage (community feed)
//   POST   /v1/hub/communities/{id}/join         → MembershipResult
//   DELETE /v1/hub/communities/{id}/membership   → MembershipResult (leave)
//
// The community feed is Discussions ONLY (ADR-0001) — never Posts, never a
// hybrid. Deep links are built server-side; the client only navigates.
package communitybff

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"
	"time"

	"github.com/go-chi/chi/v5"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

const (
	defaultUpstreamTimeout = 4 * time.Second
	membersPageCap         = 30
	discussionsPageCap     = 20
)

type Handlers struct {
	agg     *Aggregator
	social  SocialGateway
	cache   *StatsCache
	metrics *Metrics
	limiter *rateLimiter
	timeout time.Duration
}

func NewHandlers(social SocialGateway, agg *Aggregator, cache *StatsCache, m *Metrics) *Handlers {
	return &Handlers{
		agg:     agg,
		social:  social,
		cache:   cache,
		metrics: m,
		limiter: newRateLimiter(60, 10*time.Second), // 60 community reads / 10s / user
		timeout: defaultUpstreamTimeout,
	}
}

// ---- GET detail ----

func (h *Handlers) GetDetail(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	h.metrics.request("detail")
	defer func() { h.metrics.latency.WithLabelValues("detail").Observe(time.Since(start).Seconds()) }()

	viewer, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "")
		return
	}
	id := chi.URLParam(r, "community_id")
	if id == "" {
		writeErr(w, http.StatusBadRequest, "missing_community_id", "")
		return
	}
	if !h.limiter.allow(viewer.String()) {
		h.metrics.rateLimit()
		writeErr(w, http.StatusTooManyRequests, "community_rate_limited", "")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()

	// Stats cache (user-independent). A hit skips the GetStats upstream call.
	var statsBody []byte
	if b, hit := h.cache.Get(id); hit {
		h.metrics.cacheHit()
		statsBody = b
	} else {
		h.metrics.cacheMiss()
	}
	cacheStats := func(b []byte) { h.cache.Set(id, b) }

	d, err := h.agg.Detail(ctx, id, viewer.String(), statsBody, cacheStats)
	if err != nil {
		h.writeUpstream(w, "detail", err)
		return
	}
	writeJSON(w, http.StatusOK, d)
}

// ---- GET members (cursor + optional role filter) ----

func (h *Handlers) GetMembers(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	h.metrics.request("members")
	defer func() { h.metrics.latency.WithLabelValues("members").Observe(time.Since(start).Seconds()) }()

	viewer, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "")
		return
	}
	id := chi.URLParam(r, "community_id")
	if id == "" {
		writeErr(w, http.StatusBadRequest, "missing_community_id", "")
		return
	}
	if !h.limiter.allow(viewer.String()) {
		h.metrics.rateLimit()
		writeErr(w, http.StatusTooManyRequests, "community_rate_limited", "")
		return
	}

	cursor := r.URL.Query().Get("cursor")
	roleParam := r.URL.Query().Get("role") // owner|admin|moderator|member (projection)
	roleFilter := roleFromWire(roleParam)

	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()

	resp, err := h.social.ListMembers(ctx, id, cursor, membersPageCap, roleFilter)
	if err != nil {
		h.writeUpstream(w, "members", err)
		return
	}
	out := MembersPage{Members: make([]Member, 0, len(resp.Members))}
	for _, m := range resp.Members {
		out.Members = append(out.Members, memberProfileToDTO(m))
	}
	if resp.NextCursor != nil {
		out.NextCursor = *resp.NextCursor
	}
	if roleFilter != nil {
		out.RoleFilter = roleParam
	}
	writeJSON(w, http.StatusOK, out)
}

// ---- GET discussions (community feed — Discussions ONLY) ----

func (h *Handlers) GetDiscussions(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	h.metrics.request("discussions")
	defer func() { h.metrics.latency.WithLabelValues("discussions").Observe(time.Since(start).Seconds()) }()

	viewer, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "")
		return
	}
	id := chi.URLParam(r, "community_id")
	if id == "" {
		writeErr(w, http.StatusBadRequest, "missing_community_id", "")
		return
	}
	if !h.limiter.allow(viewer.String()) {
		h.metrics.rateLimit()
		writeErr(w, http.StatusTooManyRequests, "community_rate_limited", "")
		return
	}

	cursor := r.URL.Query().Get("cursor")
	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()

	resp, err := h.social.ListDiscussions(ctx, id, cursor, discussionsPageCap)
	if err != nil {
		h.writeUpstream(w, "discussions", err)
		return
	}
	out := DiscussionsPage{Discussions: make([]Discussion, 0, len(resp.Discussions))}
	for _, d := range resp.Discussions {
		out.Discussions = append(out.Discussions, discussionToDTO(d))
	}
	if resp.NextCursor != nil {
		out.NextCursor = *resp.NextCursor
	}
	writeJSON(w, http.StatusOK, out)
}

// ---- POST join / DELETE leave ----

func (h *Handlers) Join(w http.ResponseWriter, r *http.Request) {
	h.mutateMembership(w, r, "join")
}

func (h *Handlers) Leave(w http.ResponseWriter, r *http.Request) {
	h.mutateMembership(w, r, "leave")
}

func (h *Handlers) mutateMembership(w http.ResponseWriter, r *http.Request, action string) {
	start := time.Now()
	h.metrics.request(action)
	defer func() { h.metrics.latency.WithLabelValues(action).Observe(time.Since(start).Seconds()) }()

	viewer, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "")
		return
	}
	id := chi.URLParam(r, "community_id")
	if id == "" {
		writeErr(w, http.StatusBadRequest, "missing_community_id", "")
		return
	}
	if !h.limiter.allow(viewer.String()) {
		h.metrics.rateLimit()
		writeErr(w, http.StatusTooManyRequests, "community_rate_limited", "")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()

	var viewerRole, membershipStatus string
	switch action {
	case "join":
		// The user is derived from the verified session — never the body.
		m, err := h.social.Join(ctx, id, viewer.String())
		if err != nil {
			h.writeUpstream(w, "join", err)
			return
		}
		viewerRole, membershipStatus = roleToWire(m.Role), statusMember
	case "leave":
		if err := h.social.Leave(ctx, id, viewer.String()); err != nil {
			// Owner-leave is blocked by the domain (FailedPrecondition).
			h.writeUpstream(w, "leave", err)
			return
		}
		viewerRole, membershipStatus = roleNone, statusNotMember
	}

	// Invalidate the shared stats cache: member_count changed.
	h.cache.Set(id, nil)

	// Refresh counters + capabilities so the client updates without re-fetch.
	res := MembershipResult{
		CommunityID:      id,
		ViewerRole:       viewerRole,
		MembershipStatus: membershipStatus,
		Capabilities:     capabilitiesFor(viewerRole, membershipStatus == statusMember, true),
	}
	if st, err := h.social.GetStats(ctx, id); err == nil {
		res.MemberCount = st.MemberCount
		h.cache.Set(id, encodeCacheStats(RoleCounts{
			Owner: st.RoleCounts.GetOwner(), Admin: st.RoleCounts.GetAdmin(),
			Moderator: st.RoleCounts.GetModerator(), Member: st.RoleCounts.GetMember(),
		}, st.MemberCount, st.DiscussionCount))
	}
	writeJSON(w, http.StatusOK, res)
}

// ---- upstream error mapping (gRPC → HTTP) ----

func (h *Handlers) writeUpstream(w http.ResponseWriter, endpoint string, err error) {
	s, _ := status.FromError(err)
	switch s.Code() {
	case codes.NotFound:
		writeErr(w, http.StatusNotFound, "community_not_found", "")
	case codes.AlreadyExists:
		writeErr(w, http.StatusConflict, "already_member", "")
	case codes.FailedPrecondition:
		// e.g. owner cannot leave without transferring ownership.
		writeErr(w, http.StatusConflict, "membership_conflict", s.Message())
	case codes.Unimplemented:
		writeErr(w, http.StatusNotImplemented, "capability_unavailable", s.Message())
	case codes.InvalidArgument:
		writeErr(w, http.StatusBadRequest, "invalid_request", s.Message())
	case codes.DeadlineExceeded:
		h.metrics.timeout(endpoint)
		writeErr(w, http.StatusGatewayTimeout, "community_upstream_timeout", "")
	case codes.Canceled:
		// client went away — nothing to write meaningfully
		writeErr(w, 499, "client_closed_request", "")
	default:
		writeErr(w, http.StatusBadGateway, "community_upstream_error", "")
	}
}

// ---- helpers ----

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

// ---- per-user fixed-window rate limiter ----

type rateLimiter struct {
	mu     sync.Mutex
	hits   map[string]*window
	max    int
	period time.Duration
	now    func() time.Time
}

type window struct {
	count   int
	resetAt time.Time
}

func newRateLimiter(max int, period time.Duration) *rateLimiter {
	return &rateLimiter{hits: map[string]*window{}, max: max, period: period, now: time.Now}
}

func (l *rateLimiter) allow(userID string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	w := l.hits[userID]
	if w == nil || now.After(w.resetAt) {
		if len(l.hits) > 10000 {
			l.hits = map[string]*window{}
		}
		l.hits[userID] = &window{count: 1, resetAt: now.Add(l.period)}
		return true
	}
	if w.count >= l.max {
		return false
	}
	w.count++
	return true
}
