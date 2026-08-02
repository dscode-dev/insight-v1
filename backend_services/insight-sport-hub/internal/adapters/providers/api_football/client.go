// Thin HTTP client over API-Football (api-sports.io v3).
//
// Stateless — owns no business state, only its config (base URL,
// API key, http.Client with timeouts). The adapter struct
// instantiates one Client at construction; tests can swap the
// http.Client via the Config.HTTPClient field.
//
// Authentication: api-sports.io accepts BOTH
//
//	x-rapidapi-key   (when accessed via RapidAPI gateway)
//	x-apisports-key  (when accessed via direct subscription)
//
// We send both — the provider silently ignores the unused one.
package api_football

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"
)

const (
	defaultBaseURL = "https://v3.football.api-sports.io"
	defaultTimeout = 10 * time.Second
)

// Config carries every knob the client needs. Required: APIKey.
// Optional: BaseURL (defaults to the production v3 host),
// HTTPClient (defaults to a fresh http.Client with sensible
// timeouts), Timeout (per-request override).
type Config struct {
	APIKey     string
	BaseURL    string
	HTTPClient *http.Client
	Timeout    time.Duration
}

type Client struct {
	apiKey  string
	baseURL string
	http    *http.Client
}

func NewClient(cfg Config) *Client {
	base := cfg.BaseURL
	if base == "" {
		base = defaultBaseURL
	}
	hc := cfg.HTTPClient
	if hc == nil {
		t := cfg.Timeout
		if t <= 0 {
			t = defaultTimeout
		}
		hc = &http.Client{Timeout: t}
	}
	return &Client{apiKey: cfg.APIKey, baseURL: base, http: hc}
}

// do executes a GET and unmarshals the standard envelope. The
// generic envelope[T] wraps every API-Football response.
//
// We return the full envelope (not just envelope.Response) so the
// caller can inspect `Errors` + `Paging`. Sprint 2 doesn't paginate
// — the free tier limits to a handful of pages anyway; pagination
// lands in Sprint 3 when polling cadence is wired.
func do[T any](ctx context.Context, c *Client, path string, query url.Values) (envelope[T], error) {
	var zero envelope[T]

	u := c.baseURL + path
	if len(query) > 0 {
		u += "?" + query.Encode()
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return zero, fmt.Errorf("api_football: build request: %w", err)
	}
	// Both header variants per the package doc.
	req.Header.Set("x-rapidapi-key", c.apiKey)
	req.Header.Set("x-apisports-key", c.apiKey)
	req.Header.Set("x-rapidapi-host", "v3.football.api-sports.io")
	req.Header.Set("Accept", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return zero, fmt.Errorf("api_football: http: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode >= 400 {
		// Read up to 1KB of the body for the operator log. We never
		// log this further out — the orchestrator's structured log
		// gets only the status code + the path.
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return zero, fmt.Errorf("api_football: http %d: %s", resp.StatusCode, string(body))
	}

	var env envelope[T]
	if err := json.NewDecoder(resp.Body).Decode(&env); err != nil {
		return zero, fmt.Errorf("api_football: decode: %w", err)
	}
	return env, nil
}

// ---- typed wrappers per endpoint ----

func (c *Client) Leagues(ctx context.Context) (envelope[[]leagueWrapper], error) {
	return do[[]leagueWrapper](ctx, c, "/leagues", nil)
}

func (c *Client) Fixtures(ctx context.Context, leagueID, season int64) (envelope[[]fixtureWrapper], error) {
	q := url.Values{}
	q.Set("league", fmt.Sprintf("%d", leagueID))
	q.Set("season", fmt.Sprintf("%d", season))
	return do[[]fixtureWrapper](ctx, c, "/fixtures", q)
}

func (c *Client) Standings(ctx context.Context, leagueID, season int64) (envelope[[]standingsWrapper], error) {
	q := url.Values{}
	q.Set("league", fmt.Sprintf("%d", leagueID))
	q.Set("season", fmt.Sprintf("%d", season))
	return do[[]standingsWrapper](ctx, c, "/standings", q)
}
