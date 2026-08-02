package middleware

import "net/http"

// SecurityHeadersConfig controls the headers SecurityHeaders applies.
// All defaults are safe-for-prod; lab can opt out of HSTS via
// `EnableHSTS: false` so a cached HSTS pin doesn't break `http://`
// local dev.
type SecurityHeadersConfig struct {
	EnableHSTS bool
	// CSP override. Empty value = use the conservative default below.
	CSP string
}

const defaultCSP = "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"

func SecurityHeaders(cfg SecurityHeadersConfig) func(http.Handler) http.Handler {
	csp := cfg.CSP
	if csp == "" {
		csp = defaultCSP
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("X-Content-Type-Options", "nosniff")
			w.Header().Set("X-Frame-Options", "DENY")
			w.Header().Set("Referrer-Policy", "strict-origin-when-cross-origin")
			w.Header().Set("Content-Security-Policy", csp)
			if cfg.EnableHSTS {
				w.Header().Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
			}
			next.ServeHTTP(w, r)
		})
	}
}
