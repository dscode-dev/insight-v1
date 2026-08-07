package httpapi

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

const testToken = "social-ops-secret"

func reached() (http.HandlerFunc, *bool) {
	hit := false
	return func(w http.ResponseWriter, r *http.Request) {
		hit = true
		w.WriteHeader(http.StatusOK)
	}, &hit
}

func request(token, operatorID string) *http.Request {
	r := httptest.NewRequest(http.MethodGet, "/console/social/users", nil)
	if token != "" {
		r.Header.Set(headerOpsToken, token)
	}
	if operatorID != "" {
		r.Header.Set(headerOperatorID, operatorID)
	}
	return r
}

// The whole point: the fifteen read routes used to require nothing, because
// the network was the protection. Exposing Social to the Control Plane removes
// that boundary, and an unauthenticated read plane on a public ingress hands
// over every user, post and comment in the platform.
func TestReadsRequireTheToken(t *testing.T) {
	handler, hit := reached()
	rec := httptest.NewRecorder()
	RequireConsoleToken(testToken, false, handler)(rec, request("", ""))

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("code = %d, want 401", rec.Code)
	}
	if *hit {
		t.Fatal("an unauthenticated read reached the handler")
	}
}

func TestReadsAcceptTheToken(t *testing.T) {
	handler, hit := reached()
	rec := httptest.NewRecorder()
	RequireConsoleToken(testToken, false, handler)(rec, request(testToken, ""))

	if rec.Code != http.StatusOK || !*hit {
		t.Fatalf("code = %d hit = %v", rec.Code, *hit)
	}
}

func TestWrongTokenIsRefused(t *testing.T) {
	handler, hit := reached()
	rec := httptest.NewRecorder()
	RequireConsoleToken(testToken, false, handler)(rec, request("wrong", ""))

	if rec.Code != http.StatusUnauthorized || *hit {
		t.Fatalf("code = %d hit = %v", rec.Code, *hit)
	}
}

// A write with no named actor produces an audit row that cannot answer "who".
func TestWritesRequireAnOperator(t *testing.T) {
	handler, hit := reached()
	rec := httptest.NewRecorder()
	RequireConsoleToken(testToken, true, handler)(rec, request(testToken, ""))

	if rec.Code != http.StatusForbidden {
		t.Fatalf("code = %d, want 403", rec.Code)
	}
	if *hit {
		t.Fatal("a write with no operator reached the handler")
	}
}

func TestWritesAcceptATokenPlusOperator(t *testing.T) {
	var seen ConsoleOperator
	handler := func(w http.ResponseWriter, r *http.Request) {
		seen, _ = OperatorFromContext(r.Context())
		w.WriteHeader(http.StatusOK)
	}
	rec := httptest.NewRecorder()
	req := request(testToken, "op-1")
	req.Header.Set(headerOperator, "darlan")
	RequireConsoleToken(testToken, true, handler)(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("code = %d, want 200", rec.Code)
	}
	// The token says the CALLER is the Control Plane; the operator says who
	// asked. Audit needs the second, and conflating them would attribute every
	// action to "the Control Plane".
	if seen.ID != "op-1" || seen.Username != "darlan" {
		t.Fatalf("operator not forwarded: %+v", seen)
	}
}

// An unset token means the surface is not configured, which is a different
// problem from a wrong credential. 401 would send an operator hunting for a
// key that no deployment has.
func TestUnconfiguredSurfaceAnswers503(t *testing.T) {
	handler, hit := reached()
	rec := httptest.NewRecorder()
	RequireConsoleToken("", false, handler)(rec, request("anything", ""))

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("code = %d, want 503", rec.Code)
	}
	if *hit {
		t.Fatal("handler ran with no token configured")
	}
}

// Whitespace-only is unset, not a one-character secret. A token that is a
// single space in a values file would otherwise "work".
func TestBlankTokenIsTreatedAsUnconfigured(t *testing.T) {
	rec := httptest.NewRecorder()
	handler, _ := reached()
	RequireConsoleToken("   ", false, handler)(rec, request("   ", ""))

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("code = %d, want 503", rec.Code)
	}
}
