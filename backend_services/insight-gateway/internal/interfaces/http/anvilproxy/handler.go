// Package anvilproxy exposes the narrow Atlas analytics route and forwards it
// to Anvil. ClickHouse credentials remain inside Anvil's environment.
package anvilproxy

import (
	"crypto/subtle"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
)

const (
	atlasKeyHeader = "X-Atlas-Anvil-Key"
	anvilKeyHeader = "X-Anvil-API-Key"
)

type Config struct {
	AtlasAPIKey string
	AnvilURL    string
	AnvilAPIKey string
	Timeout     time.Duration
}

type Handler struct {
	cfg    Config
	client *http.Client
}

func New(cfg Config) (*Handler, error) {
	base, err := url.Parse(strings.TrimRight(cfg.AnvilURL, "/"))
	if err != nil || base.Scheme == "" || base.Host == "" {
		return nil, &url.Error{Op: "parse", URL: cfg.AnvilURL, Err: err}
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 10 * time.Second
	}
	return &Handler{cfg: cfg, client: &http.Client{Timeout: cfg.Timeout}}, nil
}

func (h *Handler) MatchFeatures(w http.ResponseWriter, r *http.Request) {
	if h.cfg.AtlasAPIKey == "" {
		writeError(w, http.StatusServiceUnavailable, "atlas_anvil_route_disabled")
		return
	}
	got := r.Header.Get(atlasKeyHeader)
	if got == "" || subtle.ConstantTimeCompare(
		[]byte(got), []byte(h.cfg.AtlasAPIKey),
	) != 1 {
		writeError(w, http.StatusUnauthorized, "invalid_atlas_anvil_key")
		return
	}

	target := strings.TrimRight(h.cfg.AnvilURL, "/") +
		"/internal/features/matches/" + url.PathEscape(chi.URLParam(r, "match_id"))
	if r.URL.RawQuery != "" {
		target += "?" + r.URL.RawQuery
	}
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, target, nil)
	if err != nil {
		writeError(w, http.StatusBadGateway, "anvil_request_build_failed")
		return
	}
	req.Header.Set(anvilKeyHeader, h.cfg.AnvilAPIKey)
	req.Header.Set("X-Request-Id", r.Header.Get("X-Request-Id"))
	resp, err := h.client.Do(req)
	if err != nil {
		writeError(w, http.StatusBadGateway, "anvil_unavailable")
		return
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		writeError(w, http.StatusBadGateway, "anvil_response_read_failed")
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(resp.StatusCode)
	_, _ = w.Write(body)
}

func writeError(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}
