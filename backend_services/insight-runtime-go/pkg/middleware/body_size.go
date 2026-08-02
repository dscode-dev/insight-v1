package middleware

import (
	"net/http"
)

// BodyLimit refuses requests whose Content-Length exceeds maxBytes
// with a 413 before the body is read. For chunked uploads (no
// Content-Length), io.LimitReader wraps the body so the underlying
// reader terminates at the cap.
//
// Per-route limits supersede the default — auth bodies are tiny, BFF
// aggregations can be larger.
func BodyLimit(maxBytes int64) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.ContentLength > maxBytes {
				http.Error(w, "request_entity_too_large", http.StatusRequestEntityTooLarge)
				return
			}
			r.Body = http.MaxBytesReader(w, r.Body, maxBytes)
			next.ServeHTTP(w, r)
		})
	}
}
