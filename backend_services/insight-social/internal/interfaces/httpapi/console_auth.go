package httpapi

import (
	"context"
	"crypto/subtle"
	"net/http"
	"strings"
)

// Console authentication for Social's administrative surface.
//
// WHY THIS EXISTS. The fifteen `/console/social/*` READ routes had no check of
// any kind. Only the two write routes verified SOCIAL_OPS_TOKEN. That was
// defensible while the sole route in was the Gateway, inside the cluster,
// after operator auth — the reads were behind a network boundary and the
// comment in main.go said so.
//
// It stops being defensible the moment Social is reachable from outside the
// cluster, which is exactly what insight-context.md v2.0 asks for: the Insight
// Control Plane administers Social, and it runs on the Robozão. Publishing an
// ingress in front of fifteen unauthenticated reads would expose every user,
// post, comment and community in the platform to anyone who found the
// hostname.
//
// So the token is now required on the whole surface, reads included. An
// inconsistent rule is worse than a strict one: whoever adds route sixteen
// copies whichever neighbour they happened to read.
//
// WHAT THE TOKEN IS AND IS NOT. It authenticates the CALLER — it proves the
// request came from the Control Plane. It says nothing about which operator
// asked, which is why the operator travels separately in X-Operator-Id and is
// what audit records. Conflating the two would make every action attributable
// only to "the Control Plane".

const (
	headerOpsToken   = "X-Ops-Token"
	headerOperatorID = "X-Operator-Id"
	headerOperator   = "X-Operator"
)

type operatorCtxKey struct{}

// ConsoleOperator is the operator the Control Plane says is acting.
type ConsoleOperator struct {
	ID       string
	Username string
}

// OperatorFromContext returns the acting operator, if the request came through
// RequireConsoleToken.
func OperatorFromContext(ctx context.Context) (ConsoleOperator, bool) {
	op, ok := ctx.Value(operatorCtxKey{}).(ConsoleOperator)
	return op, ok
}

// RequireConsoleToken guards the administrative surface.
//
// `requireOperator` is true for mutations: a write with no named actor
// produces an audit row that cannot answer "who". Reads do not need it —
// requiring an operator to list posts would break nothing but would invent a
// rule the callers have no reason to expect.
func RequireConsoleToken(token string, requireOperator bool, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if strings.TrimSpace(token) == "" {
			// Unset token means the surface is not configured, which is
			// different from a bad token: 503 says "this service is not set
			// up for that", 401 says "your credential is wrong". Answering
			// 401 here would send an operator hunting for a key that no
			// deployment has.
			writeJSON(w, http.StatusServiceUnavailable,
				map[string]any{"detail": "social_console_disabled"})
			return
		}
		got := r.Header.Get(headerOpsToken)
		// Constant-time: a plain == returns on the first differing byte, and
		// the timing difference leaks the token one byte at a time.
		if got == "" || subtle.ConstantTimeCompare([]byte(got), []byte(token)) != 1 {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "invalid_ops_token"})
			return
		}

		operator := ConsoleOperator{
			ID:       strings.TrimSpace(r.Header.Get(headerOperatorID)),
			Username: strings.TrimSpace(r.Header.Get(headerOperator)),
		}
		if requireOperator && operator.ID == "" {
			writeJSON(w, http.StatusForbidden,
				map[string]any{"detail": "operator_identity_required"})
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), operatorCtxKey{}, operator)))
	}
}
