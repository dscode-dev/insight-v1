// Package middleware bundles the request-shaped concerns that every
// Insight Go service applies. Each middleware is composable and
// independent — services pick what they need rather than installing
// the bundle blindly.
package middleware

import (
	"context"
	"net/http"

	"github.com/google/uuid"
	"github.com/rs/zerolog"
)

type ctxKey struct{ name string }

var requestIDKey = ctxKey{"request_id"}

// RequestIDFromContext returns the request id carried by ctx, or "".
func RequestIDFromContext(ctx context.Context) string {
	v, _ := ctx.Value(requestIDKey).(string)
	return v
}

// RequestID assigns each request a UUID v4 unless one already arrived
// in the `X-Request-Id` header — clients (Flutter) generate their own
// for client-side correlation, and we honour them.
//
// The id is:
//   - Stored in request context (read via RequestIDFromContext).
//   - Echoed back in the `X-Request-Id` response header.
//   - Attached to the per-request zerolog sub-logger so every log
//     line carries the id automatically.
func RequestID() func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			id := r.Header.Get("X-Request-Id")
			if id == "" {
				id = uuid.NewString()
			}
			ctx := context.WithValue(r.Context(), requestIDKey, id)

			// Annotate the contextual logger.
			logger := zerolog.Ctx(ctx).With().Str("request_id", id).Logger()
			ctx = logger.WithContext(ctx)

			w.Header().Set("X-Request-Id", id)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}
