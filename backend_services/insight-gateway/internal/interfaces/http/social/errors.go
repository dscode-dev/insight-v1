// gRPC error → HTTP code mapping for the social BFF handlers.
//
// One mapper for every handler so the wire behaviour is consistent.
// Internal errors don't leak details to the client — log them
// server-side and return a generic 500.
package social

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/rs/zerolog"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// errAuthMissing is the sentinel handlers return when an authmw-gated
// route was reached without a user_id in ctx. Should be unreachable
// if the route is wired correctly; surfaced as 401 rather than 500
// so a misconfiguration produces a precise wire signal.
var errAuthMissing = errors.New("authmw was not applied to this route")

type errorBody struct {
	Error  string `json:"error"`
	Detail string `json:"detail,omitempty"`
}

// writeGrpcError converts a gRPC status error from insight-social
// into an HTTP response. Maps codes to standard HTTP semantics:
//
//	NotFound            → 404
//	AlreadyExists       → 409
//	InvalidArgument     → 400
//	FailedPrecondition  → 412
//	Unauthenticated     → 401  (won't happen — gateway is the authn boundary,
//	                             but mapped for completeness)
//	PermissionDenied    → 403
//	DeadlineExceeded    → 504
//	Unavailable         → 503
//	Unimplemented       → 501  (would surface for any social.v1 RPC the
//	                             gateway calls but social-go hasn't shipped)
//	anything else       → 500  (logged with full status; client gets generic)
func writeGrpcError(w http.ResponseWriter, r *http.Request, err error) {
	logger := zerolog.Ctx(r.Context())

	// Local sentinels first — they take precedence over grpc status
	// classification so misconfiguration produces a precise wire signal.
	if errors.Is(err, errAuthMissing) {
		logger.Error().Err(err).Msg("social_auth_middleware_missing")
		writeError(w, http.StatusUnauthorized, "auth_required", "")
		return
	}

	st, ok := status.FromError(err)
	if !ok {
		// Non-gRPC error (e.g. context cancelled, dial failure that
		// the client surface didn't wrap). Same generic 500 shape.
		logger.Error().Err(err).Msg("social_non_grpc_error")
		writeError(w, http.StatusInternalServerError, "internal_error", "")
		return
	}

	httpCode := grpcCodeToHTTP(st.Code())
	if httpCode >= 500 {
		// Log full message for server-side debug; the wire stays generic.
		logger.Error().
			Str("grpc_code", st.Code().String()).
			Str("grpc_message", st.Message()).
			Msg("social_upstream_error")
		writeError(w, httpCode, "upstream_error", "")
		return
	}
	// 4xx — surface the upstream message verbatim (already
	// client-facing in the social handler's status.Error calls).
	writeError(w, httpCode, st.Code().String(), st.Message())
}

func grpcCodeToHTTP(c codes.Code) int {
	switch c {
	case codes.OK:
		return http.StatusOK
	case codes.InvalidArgument:
		return http.StatusBadRequest
	case codes.Unauthenticated:
		return http.StatusUnauthorized
	case codes.PermissionDenied:
		return http.StatusForbidden
	case codes.NotFound:
		return http.StatusNotFound
	case codes.AlreadyExists:
		return http.StatusConflict
	case codes.FailedPrecondition:
		return http.StatusPreconditionFailed
	case codes.ResourceExhausted:
		return http.StatusTooManyRequests
	case codes.DeadlineExceeded:
		return http.StatusGatewayTimeout
	case codes.Unavailable:
		return http.StatusServiceUnavailable
	case codes.Unimplemented:
		return http.StatusNotImplemented
	default:
		return http.StatusInternalServerError
	}
}

func writeError(w http.ResponseWriter, status int, code, detail string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(errorBody{Error: code, Detail: detail})
}

// writeJSON writes a successful response. Marshalling errors are
// internal — log and emit a 500 (the handler MUST NOT have committed
// the status code before calling).
func writeJSON(w http.ResponseWriter, r *http.Request, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	buf, err := json.Marshal(body)
	if err != nil {
		zerolog.Ctx(r.Context()).Error().Err(err).Msg("social_marshal_failed")
		writeError(w, http.StatusInternalServerError, "internal_error", "")
		return
	}
	w.WriteHeader(status)
	if _, err := w.Write(buf); err != nil {
		// Client likely hung up — debug only, not a server fault.
		zerolog.Ctx(r.Context()).Debug().Err(err).Msg("social_write_failed")
	}
}

// errIs is a small predicate used in handlers when we want to surface
// a specific upstream error code (e.g. NotFound on a missing community
// short-circuiting the 200 happy path).
func errIs(err error, c codes.Code) bool {
	if err == nil {
		return false
	}
	st, ok := status.FromError(err)
	if !ok {
		return false
	}
	return st.Code() == c
}
