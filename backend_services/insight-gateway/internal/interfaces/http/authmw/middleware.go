// Package authmw provides a chi middleware that extracts the
// authenticated user_id from a `Authorization: Bearer <jwt>` header
// using the gateway's existing JWT codec.
//
// Lives in its own package (not under interfaces/http/auth) so the
// social BFF handlers can depend on it without creating a circular
// import back into the auth handler package.
//
// Why a tiny package instead of inlining: every new authenticated
// route under interfaces/http/* needs the same `current_user_id`
// dependency the legacy BFF used via FastAPI Depends. Centralising the
// extraction (and the failure shape) makes it impossible to forget
// the auth gate on a handler.
package authmw

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/google/uuid"

	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

type ctxKey int

const userIDKey ctxKey = 0

// TokenDecoder is the minimal subset of jwt.Codec the middleware needs.
// Defined here (not imported from domain/auth) so the middleware can
// also accept test doubles.
type TokenDecoder interface {
	DecodeAccess(token string) (uuid.UUID, error)
}

// Require wraps next, gating access on a valid `Authorization: Bearer
// <jwt>` header. On failure responds 401 + `{"error":"<code>"}` and
// does NOT call next. On success injects the decoded user_id into the
// request context (retrievable via UserID).
func Require(decoder TokenDecoder) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			raw := r.Header.Get("Authorization")
			if len(raw) < 8 || !strings.EqualFold(raw[:7], "Bearer ") {
				writeUnauthorized(w, "missing_bearer_token")
				return
			}
			tok := strings.TrimSpace(raw[7:])
			if tok == "" {
				writeUnauthorized(w, "missing_bearer_token")
				return
			}
			userID, err := decoder.DecodeAccess(tok)
			if err != nil {
				// Don't leak the underlying jwt error (could give an
				// attacker a parse oracle); same posture as SSE.
				writeUnauthorized(w, "invalid_access_token")
				return
			}
			ctx := context.WithValue(r.Context(), userIDKey, userID)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// UserID returns the authenticated user id put into ctx by Require.
// Bool is false when the middleware wasn't applied (programmer error;
// handler shouldn't be reachable without Require).
func UserID(ctx context.Context) (uuid.UUID, bool) {
	v, ok := ctx.Value(userIDKey).(uuid.UUID)
	return v, ok
}

func writeUnauthorized(w http.ResponseWriter, code string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusUnauthorized)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": code})
}

// Compile-time sanity check: domain Codec satisfies TokenDecoder.
// (Suppresses unused warning when nothing else references domauth.)
var _ TokenDecoder = (domauth.TokenCodec)(nil)

// WithUserID injects a user id into ctx exactly like Require does —
// FOR TESTS ONLY (handler tests need an authenticated context without
// running the full JWT path).
func WithUserID(ctx context.Context, id uuid.UUID) context.Context {
	return context.WithValue(ctx, userIDKey, id)
}
