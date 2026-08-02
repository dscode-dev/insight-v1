// Public Search HTTP surface (the ONLY discovery contract clients see).
//
// Every handler: verified user (authmw) → per-user rate limit → per-user cache
// → orchestration → Gateway-owned moderation lens (the same ViewFor split the
// feed uses: banned/suspended users and admin-hidden posts NEVER appear in
// search) → canonical response. Correlation id: the inbound X-Request-Id is
// reused across the whole fan-out.

package searchbff

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

// ---- moderation lens (narrow ports; nil-safe like the social BFF) ----

type ModerationView interface {
	AuthorHidden(id string) bool
	PostHidden(id string) bool
}

type ModerationLens interface {
	SearchView(ctx context.Context, viewerID string) (ModerationView, error)
}

// ---- per-user rate limiter (fixed window) ----

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
		if len(l.hits) > 10000 { // bound the map: drop stale windows wholesale
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

// ---- handlers ----

type Handlers struct {
	client  *SocialClient
	agg     *Aggregator
	cache   *Cache
	mod     ModerationLens // nil ⇒ no lens (never in production)
	limiter *rateLimiter
	metrics *Metrics
}

func NewHandlers(client *SocialClient, agg *Aggregator, cache *Cache, mod ModerationLens, m *Metrics) *Handlers {
	return &Handlers{
		client: client, agg: agg, cache: cache, mod: mod,
		limiter: newRateLimiter(30, 10*time.Second), // 30 searches / 10s / user
		metrics: m,
	}
}

const perCategoryTimeout = 4 * time.Second

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeRaw(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

// begin authenticates, rate-limits and assembles the fan-out call context.
func (h *Handlers) begin(w http.ResponseWriter, r *http.Request, category string) (callCtx, bool) {
	uid, ok := authmw.UserID(r.Context())
	if !ok {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "unauthenticated"})
		return callCtx{}, false
	}
	userID := uid.String()
	if !h.limiter.allow(userID) {
		h.metrics.RateLimited()
		writeJSON(w, http.StatusTooManyRequests, map[string]string{"detail": "search_rate_limited"})
		return callCtx{}, false
	}
	h.metrics.Request(category)
	return callCtx{
		UserID:        userID,
		CorrelationID: r.Header.Get("X-Request-Id"), // ONE id for the whole fan-out
	}, true
}

// upstreamErr maps orchestration failures to canonical statuses.
func (h *Handlers) upstreamErr(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, context.Canceled) || errors.Is(r.Context().Err(), context.Canceled):
		h.metrics.Cancelled()
		// Client is gone — status is moot, but keep the connection teardown clean.
		writeJSON(w, 499, map[string]string{"detail": "client_cancelled"})
	case errors.Is(err, context.DeadlineExceeded):
		writeJSON(w, http.StatusGatewayTimeout, map[string]string{"detail": "search_timeout"})
	case errors.Is(err, errUpstreamStatus) && strings.Contains(err.Error(), " 400 "):
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_search_request"})
	case errors.Is(err, ErrAllCategoriesFailed):
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "search_unavailable"})
	default:
		writeJSON(w, http.StatusBadGateway, map[string]string{"detail": "search_upstream_error"})
	}
}

// applyLens drops cards the viewer must not see (Gateway-owned moderation):
// users → banned/suspended/blocked authors; posts → admin-hidden posts OR
// hidden authors. Filtering may shrink a page below limit — the same honest
// behaviour the feed has. Fail-open on lens error (read path), like the feed.
func (h *Handlers) applyLens(ctx context.Context, viewerID string, cards []Card) []Card {
	if h.mod == nil {
		return cards
	}
	view, err := h.mod.SearchView(ctx, viewerID)
	if err != nil || view == nil {
		return cards
	}
	kept := cards[:0]
	for _, c := range cards {
		switch c.EntityType {
		case "user":
			if view.AuthorHidden(c.EntityID) {
				continue
			}
		case "post":
			if view.PostHidden(c.EntityID) {
				continue
			}
			var p PublicPost
			if err := json.Unmarshal(c.Data, &p); err == nil && view.AuthorHidden(p.AuthorID) {
				continue
			}
		}
		kept = append(kept, c)
	}
	return kept
}

// Category returns the handler for one category endpoint
// (GET /v1/search/{category}?q=&limit=&cursor=).
func (h *Handlers) Category(category string, fetch Fetcher) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		cc, ok := h.begin(w, r, category)
		if !ok {
			return
		}
		qs := r.URL.Query()
		q, cursor := qs.Get("q"), qs.Get("cursor")
		limit, _ := strconv.Atoi(qs.Get("limit"))

		key := h.cache.Key(cc.UserID, category, q, cursor, limit)
		if body, hit := h.cache.Get(key); hit {
			h.metrics.CacheHit()
			writeRaw(w, http.StatusOK, body)
			return
		}
		h.metrics.CacheMiss()

		ctx, cancel := context.WithTimeout(r.Context(), perCategoryTimeout)
		defer cancel()
		page, err := fetch(ctx, cc, q, limit, cursor)
		if err != nil {
			h.upstreamErr(w, r, err)
			return
		}
		page.Cards = h.applyLens(r.Context(), cc.UserID, page.Cards)
		if len(page.Cards) == 0 {
			h.metrics.Empty(category)
		}
		resp := CategoryResponse{Query: q, Category: category, Items: page.Cards, NextCursor: page.NextCursor}
		if resp.Items == nil {
			resp.Items = []Card{}
		}
		body, _ := json.Marshal(resp)
		h.cache.Set(key, body)
		h.metrics.Latency(category, time.Since(start).Seconds())
		writeRaw(w, http.StatusOK, body)
	}
}

// All handles GET /v1/search/all?q= — the aggregated discovery view.
func (h *Handlers) All(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	cc, ok := h.begin(w, r, "all")
	if !ok {
		return
	}
	q := r.URL.Query().Get("q")

	key := h.cache.Key(cc.UserID, "all", q, "", 0)
	if body, hit := h.cache.Get(key); hit {
		h.metrics.CacheHit()
		writeRaw(w, http.StatusOK, body)
		return
	}
	h.metrics.CacheMiss()

	resp, err := h.agg.All(r.Context(), cc, q)
	if err != nil {
		h.upstreamErr(w, r, err)
		return
	}
	resp.Items = h.applyLens(r.Context(), cc.UserID, resp.Items)
	if resp.Partial {
		h.metrics.Partial()
	}
	if len(resp.Items) == 0 {
		h.metrics.Empty("all")
	}
	body, _ := json.Marshal(resp)
	// Partial responses are NOT cached: a transiently failed category must not
	// be pinned as missing for the TTL.
	if !resp.Partial {
		h.cache.Set(key, body)
	}
	h.metrics.Latency("all", time.Since(start).Seconds())
	writeRaw(w, http.StatusOK, body)
}

// Capabilities handles GET /v1/search/capabilities — Social's contract
// ENRICHED with the Gateway-owned temporarily_unavailable dimension. If the
// upstream is down, the six known categories are reported temporarily
// unavailable (the contract itself stays serveable — honest degradation).
func (h *Handlers) Capabilities(w http.ResponseWriter, r *http.Request) {
	cc, ok := h.begin(w, r, "capabilities")
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), perCategoryTimeout)
	defer cancel()
	enabled, blocked, trending, err := h.client.Capabilities(ctx, cc)
	if err != nil {
		writeJSON(w, http.StatusOK, CapabilitiesResponse{
			Enabled:                []string{},
			Blocked:                map[string]string{},
			TemporarilyUnavailable: append([]string{}, CategoryOrder...),
			Trending:               "UNAVAILABLE",
		})
		return
	}
	writeJSON(w, http.StatusOK, CapabilitiesResponse{
		Enabled:                enabled,
		Blocked:                blocked,
		TemporarilyUnavailable: []string{},
		Trending:               trending,
	})
}

// History / ClearHistory — the Gateway is the ONLY public history contract.
func (h *Handlers) History(w http.ResponseWriter, r *http.Request) {
	cc, ok := h.begin(w, r, "history")
	if !ok {
		return
	}
	body, err := h.client.History(r.Context(), cc)
	if err != nil {
		h.upstreamErr(w, r, err)
		return
	}
	writeRaw(w, http.StatusOK, body)
}

func (h *Handlers) ClearHistory(w http.ResponseWriter, r *http.Request) {
	cc, ok := h.begin(w, r, "history")
	if !ok {
		return
	}
	body, err := h.client.ClearHistory(r.Context(), cc)
	if err != nil {
		h.upstreamErr(w, r, err)
		return
	}
	writeRaw(w, http.StatusOK, body)
}
