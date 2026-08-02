// CONSOLE-SOCIAL-A1 — operator-authed read proxy to the internal Social HTTP
// console read plane (/console/social/*). The browser never reaches Social; the
// Console BFF calls the Gateway, the Gateway authenticates the operator session
// and forwards a GET to the internal Social port. Read-only. No client actor
// trust, no service token echoed to the caller, correlation propagated.

package console

import (
	"io"
	"net/http"
	"strings"
)

const maxSocialProxyBody = 4 << 20 // 4 MiB cap

// SocialConsoleProxy maps GET /v1/console/social/<sub> → SOCIAL_HTTP/console/social/<sub>.
func (h *Handlers) SocialConsoleProxy(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireOperator(w, r); !ok {
		return
	}
	if h.socialHTTP == "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"detail": "social_read_plane_unconfigured"})
		return
	}
	// /v1/console/social/... → /console/social/... (fixed prefix; never a caller-chosen host).
	sub := strings.TrimPrefix(r.URL.Path, "/v1")
	if !strings.HasPrefix(sub, "/console/social/") {
		writeJSON(w, http.StatusNotFound, map[string]any{"detail": "not_found"})
		return
	}
	target := h.socialHTTP + sub
	if r.URL.RawQuery != "" {
		target += "?" + r.URL.RawQuery
	}
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, target, nil)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]any{"detail": "social_proxy_build_failed"})
		return
	}
	req.Header.Set("Accept", "application/json")
	if rid := r.Header.Get("X-Request-Id"); rid != "" {
		req.Header.Set("X-Request-Id", rid)
	}
	resp, err := h.httpc.Do(req)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]any{"detail": "social_unavailable"})
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, maxSocialProxyBody))
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(resp.StatusCode)
	_, _ = w.Write(body)
}
