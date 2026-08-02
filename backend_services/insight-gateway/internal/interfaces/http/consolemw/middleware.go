// Package consolemw guards the Gateway's admin surface (Store-A moderation
// center) with the shared Console service token. The Console BFF sends it as
// `X-Console-Service-Token`; the Gateway compares it (constant-time) against
// CONSOLE_SERVICE_TOKEN. Only the Console server (never a browser) holds it.
package consolemw

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
)

const headerName = "X-Console-Service-Token"

// Require gates next on a valid console service token. An empty configured
// token DISABLES the admin surface (every request 503) — fail closed, so a
// misconfigured deploy never exposes moderation actions unauthenticated.
func Require(configuredToken string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if configuredToken == "" {
				writeErr(w, http.StatusServiceUnavailable, "console_admin_disabled")
				return
			}
			got := r.Header.Get(headerName)
			if got == "" || subtle.ConstantTimeCompare([]byte(got), []byte(configuredToken)) != 1 {
				writeErr(w, http.StatusUnauthorized, "invalid_console_token")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

func writeErr(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": code})
}
