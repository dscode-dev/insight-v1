// Package competitions proxies the Featured Competitions Rail endpoint to
// insight-social (AZTECA-HOME-A). The Azteca mobile client talks to the Gateway
// only; insight-social remains the source of truth for competitions, ordering
// and the `featured` flag. This is a thin read-only pass-through — no business
// rules live here.
package competitions

import (
	"context"
	"io"
	"net/http"
	"strings"
	"time"
)

type Handler struct {
	socialBase string
	client     *http.Client
}

func New(socialHTTPBaseURL string) *Handler {
	return &Handler{
		socialBase: strings.TrimRight(socialHTTPBaseURL, "/"),
		client:     &http.Client{Timeout: 6 * time.Second},
	}
}

// Highlights handles GET /v1/competitions/highlights by forwarding to
// insight-social's /competitions/highlights and streaming the JSON back. On any
// upstream failure it returns an empty list (the client shows its empty state)
// rather than a hard error — the rail must never break the Home screen.
func (h *Handler) Highlights(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if h.socialBase == "" {
		writeEmpty(w, "social_http_not_configured")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, h.socialBase+"/competitions/highlights", nil)
	if err != nil {
		writeEmpty(w, "request_build_failed")
		return
	}
	resp, err := h.client.Do(req)
	if err != nil {
		writeEmpty(w, "social_unreachable")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		writeEmpty(w, "social_status_"+resp.Status)
		return
	}
	w.WriteHeader(http.StatusOK)
	_, _ = io.Copy(w, resp.Body)
}

func writeEmpty(w http.ResponseWriter, detail string) {
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"competitions":[],"detail":"` + detail + `"}`))
}
