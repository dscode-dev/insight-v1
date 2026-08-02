package middleware

import (
	"net/http"
	"runtime/debug"

	"github.com/rs/zerolog"
)

// Recovery catches panics in downstream handlers and turns them into a
// 500 response without crashing the process. The stack trace is
// emitted at error level so PagerDuty/Sentry can pick it up.
func Recovery() func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if rec := recover(); rec != nil {
					logger := zerolog.Ctx(r.Context())
					logger.Error().
						Interface("panic", rec).
						Str("stack", string(debug.Stack())).
						Msg("handler_panic")
					http.Error(w, "internal_error", http.StatusInternalServerError)
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}
