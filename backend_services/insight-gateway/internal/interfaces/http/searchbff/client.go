// Internal Social search client. Every call: forwards the VERIFIED user
// (X-User-Id) and reuses the ONE correlation id of the inbound request
// (X-Request-Id) — fan-out never mints new ids. Requests are built with the
// caller's context, so client disconnect / global timeout cancels every
// in-flight upstream call immediately.

package searchbff

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const maxUpstreamBody = 1 << 20 // 1 MiB cap per category response

var errUpstreamStatus = errors.New("search_upstream_status")

// SocialClient talks to Social's internal /search/* surface.
type SocialClient struct {
	base string
	http *http.Client
}

func NewSocialClient(socialHTTPBase string) *SocialClient {
	return &SocialClient{
		base: strings.TrimRight(socialHTTPBase, "/"),
		// No client-level timeout: per-request budgets come from the CONTEXT
		// (global search timeout / client cancellation own the lifecycle).
		http: &http.Client{},
	}
}

// callCtx carries the identity + correlation the fan-out must reuse.
type callCtx struct {
	UserID        string
	CorrelationID string
}

type socialEnvelope struct {
	Items      []json.RawMessage `json:"items"`
	NextCursor string            `json:"next_cursor"`
}

// get performs one internal search GET and returns the raw items + cursor.
func (c *SocialClient) get(ctx context.Context, cc callCtx, path string, q url.Values) (socialEnvelope, error) {
	if c.base == "" {
		return socialEnvelope{}, errors.New("social_http_not_configured")
	}
	u := c.base + path
	if enc := q.Encode(); enc != "" {
		u += "?" + enc
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return socialEnvelope{}, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("X-User-Id", cc.UserID)
	if cc.CorrelationID != "" {
		req.Header.Set("X-Request-Id", cc.CorrelationID) // SAME id, every call
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return socialEnvelope{}, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxUpstreamBody))
	if err != nil {
		return socialEnvelope{}, err
	}
	if resp.StatusCode != http.StatusOK {
		return socialEnvelope{}, fmt.Errorf("%w: %d %s", errUpstreamStatus, resp.StatusCode, clipBody(body))
	}
	var env socialEnvelope
	if err := json.Unmarshal(body, &env); err != nil {
		return socialEnvelope{}, fmt.Errorf("search_upstream_decode: %w", err)
	}
	return env, nil
}

func clipBody(b []byte) string {
	s := string(b)
	if len(s) > 200 {
		return s[:200]
	}
	return s
}

// CategoryPage is one mapped public page for a category.
type CategoryPage struct {
	Cards      []Card
	NextCursor string
}

// fetchCategory decodes Social items into the Gateway-owned public payload T
// (compile-time mapping — internal fields can never leak), then wraps each in a
// public Card with entity_type/entity_id/deep_link.
func fetchCategory[T any](
	ctx context.Context, c *SocialClient, cc callCtx,
	category, q string, limit int, cursor string,
	idOf func(T) string,
) (CategoryPage, error) {
	vals := url.Values{}
	vals.Set("q", q)
	if limit > 0 {
		vals.Set("limit", strconv.Itoa(limit))
	}
	if cursor != "" {
		vals.Set("cursor", cursor)
	}
	env, err := c.get(ctx, cc, "/search/"+category, vals)
	if err != nil {
		return CategoryPage{}, err
	}
	cards := make([]Card, 0, len(env.Items))
	et := entityTypeFor[category]
	for _, raw := range env.Items {
		var item T
		if err := json.Unmarshal(raw, &item); err != nil {
			return CategoryPage{}, fmt.Errorf("search_map_%s: %w", category, err)
		}
		data, err := json.Marshal(item) // re-emit through the PUBLIC type only
		if err != nil {
			return CategoryPage{}, err
		}
		id := idOf(item)
		cards = append(cards, Card{
			EntityType: et,
			EntityID:   id,
			DeepLink:   deepLink(category, id),
			Data:       data,
		})
	}
	return CategoryPage{Cards: cards, NextCursor: env.NextCursor}, nil
}

// Typed category fetchers — the six public query paths.

func (c *SocialClient) Users(ctx context.Context, cc callCtx, q string, limit int, cursor string) (CategoryPage, error) {
	return fetchCategory[PublicUser](ctx, c, cc, "users", q, limit, cursor, func(u PublicUser) string { return u.ID })
}
func (c *SocialClient) Agents(ctx context.Context, cc callCtx, q string, limit int, cursor string) (CategoryPage, error) {
	return fetchCategory[PublicAgent](ctx, c, cc, "agents", q, limit, cursor, func(a PublicAgent) string { return a.ID })
}
func (c *SocialClient) Communities(ctx context.Context, cc callCtx, q string, limit int, cursor string) (CategoryPage, error) {
	return fetchCategory[PublicCommunity](ctx, c, cc, "communities", q, limit, cursor, func(x PublicCommunity) string { return x.ID })
}
func (c *SocialClient) Competitions(ctx context.Context, cc callCtx, q string, limit int, cursor string) (CategoryPage, error) {
	return fetchCategory[PublicCompetition](ctx, c, cc, "competitions", q, limit, cursor, func(x PublicCompetition) string { return x.ID })
}
func (c *SocialClient) Matches(ctx context.Context, cc callCtx, q string, limit int, cursor string) (CategoryPage, error) {
	return fetchCategory[PublicMatch](ctx, c, cc, "matches", q, limit, cursor, func(m PublicMatch) string { return m.MatchID })
}
func (c *SocialClient) Posts(ctx context.Context, cc callCtx, q string, limit int, cursor string) (CategoryPage, error) {
	return fetchCategory[PublicPost](ctx, c, cc, "posts", q, limit, cursor, func(p PublicPost) string { return p.ID })
}

// Capabilities fetches Social's capability contract (for Gateway enrichment).
func (c *SocialClient) Capabilities(ctx context.Context, cc callCtx) (enabled []string, blocked map[string]string, trending string, err error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/search/capabilities", nil)
	if err != nil {
		return nil, nil, "", err
	}
	req.Header.Set("X-User-Id", cc.UserID)
	if cc.CorrelationID != "" {
		req.Header.Set("X-Request-Id", cc.CorrelationID)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, nil, "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, nil, "", fmt.Errorf("%w: %d", errUpstreamStatus, resp.StatusCode)
	}
	var body struct {
		Enabled  []string          `json:"enabled"`
		Blocked  map[string]string `json:"blocked"`
		Trending string            `json:"trending"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, maxUpstreamBody)).Decode(&body); err != nil {
		return nil, nil, "", err
	}
	return body.Enabled, body.Blocked, body.Trending, nil
}

// History proxies the private per-user history reads/clear (the Gateway is the
// ONLY public history contract — the client never learns how Social persists it).
func (c *SocialClient) History(ctx context.Context, cc callCtx) ([]byte, error) {
	return c.rawJSON(ctx, cc, http.MethodGet, "/search/history")
}
func (c *SocialClient) ClearHistory(ctx context.Context, cc callCtx) ([]byte, error) {
	return c.rawJSON(ctx, cc, http.MethodDelete, "/search/history")
}

func (c *SocialClient) rawJSON(ctx context.Context, cc callCtx, method, path string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-User-Id", cc.UserID)
	if cc.CorrelationID != "" {
		req.Header.Set("X-Request-Id", cc.CorrelationID)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxUpstreamBody))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%w: %d", errUpstreamStatus, resp.StatusCode)
	}
	return body, nil
}
