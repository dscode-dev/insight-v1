package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// okHandler records that the request reached the protected mux and what
// identity it carried.
func okHandler(seen *Claims) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if c, found := ActorFromContext(r.Context()); found {
			*seen = c
		}
		w.WriteHeader(http.StatusOK)
	})
}

func controlPlaneRequest(method, path, token string, perms string) *http.Request {
	req := httptest.NewRequest(method, path, nil)
	req.Header.Set(headerControlPlaneToken, token)
	req.Header.Set(headerOperatorID, "op-1")
	req.Header.Set(headerOperator, "darlan")
	req.Header.Set(headerOperatorRole, "SuperAdmin")
	if perms != "" {
		req.Header.Set(headerOperatorPerms, perms)
	}
	return req
}

func TestLockedWhenNoAuthorityConfigured(t *testing.T) {
	rec := httptest.NewRecorder()
	var seen Claims
	RequireAuth(AuthConfig{}, okHandler(&seen)).
		ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/v1/agents", nil))

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("code = %d, want 503", rec.Code)
	}
	// The body must name the knob. "admin api locked" on its own sent
	// people hunting for a bug that was a missing variable.
	if !strings.Contains(rec.Body.String(), "NEXUS_CONTROL_PLANE_TOKEN") {
		t.Fatalf("body does not name the variable that unlocks it: %s", rec.Body.String())
	}
}

func TestControlPlaneTokenAccepted(t *testing.T) {
	rec := httptest.NewRecorder()
	var seen Claims
	RequireAuth(AuthConfig{ControlPlaneToken: "s3cret"}, okHandler(&seen)).
		ServeHTTP(rec, controlPlaneRequest(
			http.MethodGet, "/v1/agents", "s3cret", "console.access"))

	if rec.Code != http.StatusOK {
		t.Fatalf("code = %d, want 200 (body %s)", rec.Code, rec.Body.String())
	}
	if seen.Username != "darlan" || seen.Role != "SuperAdmin" {
		t.Fatalf("identity not forwarded: %+v", seen)
	}
	if seen.Source != "control-plane" {
		t.Fatalf("Source = %q, want control-plane", seen.Source)
	}
}

func TestControlPlaneTokenRejected(t *testing.T) {
	rec := httptest.NewRecorder()
	var seen Claims
	RequireAuth(AuthConfig{ControlPlaneToken: "s3cret"}, okHandler(&seen)).
		ServeHTTP(rec, controlPlaneRequest(
			http.MethodGet, "/v1/agents", "wrong", "console.access"))

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("code = %d, want 401", rec.Code)
	}
	if seen.Subject != "" {
		t.Fatalf("handler ran with a bad token: %+v", seen)
	}
}

func TestControlPlaneMissingTokenHeaderRejected(t *testing.T) {
	rec := httptest.NewRecorder()
	var seen Claims
	req := httptest.NewRequest(http.MethodGet, "/v1/agents", nil)
	req.Header.Set(headerOperatorPerms, "console.access")
	RequireAuth(AuthConfig{ControlPlaneToken: "s3cret"}, okHandler(&seen)).
		ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("code = %d, want 401", rec.Code)
	}
}

// A forgotten permissions header must deny, not silently allow. This is the
// difference between "the Control Plane vouched for nothing" and "the
// Control Plane vouched for everything".
func TestControlPlaneWithoutPermissionsIsDenied(t *testing.T) {
	rec := httptest.NewRecorder()
	var seen Claims
	RequireAuth(AuthConfig{ControlPlaneToken: "s3cret"}, okHandler(&seen)).
		ServeHTTP(rec, controlPlaneRequest(http.MethodGet, "/v1/agents", "s3cret", ""))

	if rec.Code != http.StatusForbidden {
		t.Fatalf("code = %d, want 403", rec.Code)
	}
	if seen.Subject != "" {
		t.Fatal("handler ran without permissions")
	}
}

// An identity with no id AND no username produces an unattributable audit
// row, so it is refused even with a valid token.
func TestControlPlaneWithoutIdentityIsDenied(t *testing.T) {
	rec := httptest.NewRecorder()
	var seen Claims
	req := httptest.NewRequest(http.MethodGet, "/v1/agents", nil)
	req.Header.Set(headerControlPlaneToken, "s3cret")
	req.Header.Set(headerOperatorPerms, "console.access")
	RequireAuth(AuthConfig{ControlPlaneToken: "s3cret"}, okHandler(&seen)).
		ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("code = %d, want 403", rec.Code)
	}
}

func TestWritesRequireConfigWrite(t *testing.T) {
	for _, tc := range []struct {
		name  string
		perms string
		want  int
	}{
		{"read permission cannot write", "console.access", http.StatusForbidden},
		{"write permission can write", "config.write", http.StatusOK},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			var seen Claims
			RequireAuth(AuthConfig{ControlPlaneToken: "s3cret"}, okHandler(&seen)).
				ServeHTTP(rec, controlPlaneRequest(
					http.MethodPost, "/v1/personas/analyst", "s3cret", tc.perms))
			if rec.Code != tc.want {
				t.Fatalf("code = %d, want %d", rec.Code, tc.want)
			}
		})
	}
}

func TestDLQReplayRequiresItsOwnPermission(t *testing.T) {
	rec := httptest.NewRecorder()
	var seen Claims
	RequireAuth(AuthConfig{ControlPlaneToken: "s3cret"}, okHandler(&seen)).
		ServeHTTP(rec, controlPlaneRequest(
			http.MethodPost, "/v1/dlq/trends/abc/replay", "s3cret", "config.write"))

	if rec.Code != http.StatusForbidden {
		t.Fatalf("code = %d, want 403 — config.write must not imply dlq.replay", rec.Code)
	}
}

// The whole point of the migration: with a Control Plane token configured,
// the Gateway is never contacted. Pointing IdentityURL at a dead port proves
// the absence of the call — if the code still reached out, this would fail
// with a connection error instead of 200.
func TestControlPlanePathNeverCallsGateway(t *testing.T) {
	rec := httptest.NewRecorder()
	var seen Claims
	cfg := AuthConfig{
		ControlPlaneToken: "s3cret",
		IdentityURL:       "http://127.0.0.1:1/v1/operator/auth/me",
	}
	RequireAuth(cfg, okHandler(&seen)).
		ServeHTTP(rec, controlPlaneRequest(
			http.MethodGet, "/v1/agents", "s3cret", "console.access"))

	if rec.Code != http.StatusOK {
		t.Fatalf("code = %d, want 200 — the Gateway was contacted", rec.Code)
	}
}

// The legacy path stays reachable for a deployment without a token yet, so
// the migration is a config change rather than a coordinated deploy.
func TestGatewayFallbackStillWorks(t *testing.T) {
	gateway := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("Authorization") != "Bearer opaque-session" {
				w.WriteHeader(http.StatusUnauthorized)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"operator":{"id":"op-1","username":"darlan",
				"email":"d@example.com","role":"SuperAdmin",
				"permissions":["console.access"]}}`))
		}))
	defer gateway.Close()

	rec := httptest.NewRecorder()
	var seen Claims
	req := httptest.NewRequest(http.MethodGet, "/v1/agents", nil)
	req.Header.Set("Authorization", "Bearer opaque-session")
	RequireAuth(AuthConfig{IdentityURL: gateway.URL}, okHandler(&seen)).
		ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("code = %d, want 200 (body %s)", rec.Code, rec.Body.String())
	}
	if seen.Source != "gateway" {
		t.Fatalf("Source = %q, want gateway", seen.Source)
	}
}

func TestParsePermissionsDropsBlanks(t *testing.T) {
	got := parsePermissions(" console.access , ,config.write,")
	if len(got) != 2 || got[0] != "console.access" || got[1] != "config.write" {
		t.Fatalf("parsePermissions = %#v", got)
	}
}
