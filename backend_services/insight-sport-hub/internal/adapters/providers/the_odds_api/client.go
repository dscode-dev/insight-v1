// Thin HTTP client over The Odds API (the-odds-api.com v4).
//
// Stateless — owns only its config (base URL, API key, http.Client
// with timeouts). The adapter struct instantiates one Client at
// construction; tests swap the transport via Config.HTTPClient or
// point Config.BaseURL at an httptest server.
//
// Authentication: The Odds API takes the key as the `apiKey` query
// parameter on every request. We never log the raw URL with the key.
package the_odds_api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	defaultBaseURL = "https://api.the-odds-api.com"
	defaultTimeout = 10 * time.Second
	oddsFormat     = "decimal"

	// Conservative defaults applied when the request leaves the
	// market/region filters empty. h2h (moneyline) + EU region is the
	// foundational market the canonical odds payload models.
	defaultMarket = "h2h"
	defaultRegion = "eu"
)

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

// get executes a GET and decodes the JSON body into out. The apiKey is
// injected here so callers never construct it. Error messages echo the
// path + status but NEVER the query string (which carries the key).
func (c *Client) get(ctx context.Context, path string, query url.Values, out any) error {
	if query == nil {
		query = url.Values{}
	}
	query.Set("apiKey", c.apiKey)

	u := c.baseURL + path + "?" + query.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return fmt.Errorf("the_odds_api: build request %s: %w", path, err)
	}
	req.Header.Set("Accept", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("the_odds_api: http %s: %w", path, err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("the_odds_api: http %d on %s: %s", resp.StatusCode, path, string(body))
	}
	if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
		return fmt.Errorf("the_odds_api: decode %s: %w", path, err)
	}
	return nil
}

// Sports lists every sport_key the account can serve. Used by
// FetchCompetitions to populate the registry's reference data.
func (c *Client) Sports(ctx context.Context) ([]sportDTO, error) {
	var out []sportDTO
	if err := c.get(ctx, "/v4/sports", nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// Odds fetches the current bookmaker quotes for one sport_key. Empty
// markets/regions fall back to the package defaults.
func (c *Client) Odds(
	ctx context.Context, sportKey string, markets, regions []string,
) ([]oddsEventDTO, error) {
	q := oddsQuery(markets, regions)
	var out []oddsEventDTO
	path := fmt.Sprintf("/v4/sports/%s/odds", url.PathEscape(sportKey))
	if err := c.get(ctx, path, q, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// HistoricalOdds fetches the snapshot at (or just before) `date`. The
// response carries the snapshot timestamp + neighbour pointers so a
// future backfill loop can walk the timeline; this client returns the
// single snapshot the caller asked for.
func (c *Client) HistoricalOdds(
	ctx context.Context, sportKey string, date time.Time, markets, regions []string,
) (historicalOddsResponse, error) {
	q := oddsQuery(markets, regions)
	q.Set("date", date.UTC().Format(time.RFC3339))
	var out historicalOddsResponse
	path := fmt.Sprintf("/v4/historical/sports/%s/odds", url.PathEscape(sportKey))
	if err := c.get(ctx, path, q, &out); err != nil {
		return historicalOddsResponse{}, err
	}
	return out, nil
}

func oddsQuery(markets, regions []string) url.Values {
	q := url.Values{}
	q.Set("oddsFormat", oddsFormat)
	q.Set("markets", joinOrDefault(markets, defaultMarket))
	q.Set("regions", joinOrDefault(regions, defaultRegion))
	return q
}

func joinOrDefault(vals []string, fallback string) string {
	clean := make([]string, 0, len(vals))
	for _, v := range vals {
		if s := strings.TrimSpace(v); s != "" {
			clean = append(clean, s)
		}
	}
	if len(clean) == 0 {
		return fallback
	}
	return strings.Join(clean, ",")
}
