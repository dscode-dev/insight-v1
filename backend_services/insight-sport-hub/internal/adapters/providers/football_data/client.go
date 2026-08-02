// Thin HTTP client over football-data.org v4.
//
// Stateless — same shape as api_football/client.go. Auth header is
// X-Auth-Token (single value, no rapidapi gateway shenanigans).
package football_data

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

const (
	defaultBaseURL = "https://api.football-data.org/v4"
	defaultTimeout = 10 * time.Second
)

// Config — required: APIKey. Optional: BaseURL, HTTPClient, Timeout.
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

func (c *Client) do(ctx context.Context, path string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return fmt.Errorf("football_data: build request: %w", err)
	}
	req.Header.Set("X-Auth-Token", c.apiKey)
	req.Header.Set("Accept", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("football_data: http: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("football_data: http %d: %s", resp.StatusCode, string(body))
	}
	if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
		return fmt.Errorf("football_data: decode: %w", err)
	}
	return nil
}

func (c *Client) Competitions(ctx context.Context) (competitionsResponse, error) {
	var out competitionsResponse
	err := c.do(ctx, "/competitions", &out)
	return out, err
}

func (c *Client) Matches(ctx context.Context, competitionCode string) (matchesResponse, error) {
	var out matchesResponse
	err := c.do(ctx, "/competitions/"+competitionCode+"/matches", &out)
	return out, err
}

func (c *Client) Standings(ctx context.Context, competitionCode string) (standingsResponse, error) {
	var out standingsResponse
	err := c.do(ctx, "/competitions/"+competitionCode+"/standings", &out)
	return out, err
}
