// Authentication for the Nexus administrative API.
//
// Nexus never mints or verifies operator credentials, owns no sessions and
// defines no roles. It consumes an identity that an upstream authority has
// already validated.
//
// WHO THAT AUTHORITY IS. Per insight-context.md v2.0 every administrative
// operation goes through the Insight Control Plane, and the Insight Gateway
// is explicitly NOT responsible for administration, operators or the console.
// So the Control Plane is the authority, and this package trusts a
// service-to-service secret plus the operator headers it forwards.
//
// The older path — introspecting an opaque session against the Gateway's
// /v1/operator/auth/me — survives ONLY as a fallback for a deployment that
// has not been given a Control Plane token yet. It is selected by
// configuration, not by a code change, so the migration needs no coordinated
// deploy.
//
// THE SPLIT OF AUTHORITY. The Control Plane decides who you are and what you
// hold (the permissions it forwards). Nexus decides what its OWN routes
// require (requiredPermission). Neither reimplements the other's half:
// putting role→permission resolution here would fork the RBAC table, and
// putting route requirements in the Control Plane would make every new Nexus
// endpoint a two-service change.
package httpapi

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
)

const (
	permissionConsoleAccess = "console.access"
	permissionConfigWrite   = "config.write"
	permissionDLQReplay     = "dlq.replay"
)

// Control Plane hop headers. Mirrors the contract the Node Agent already
// speaks, so both internal services are reached the same way.
const (
	headerControlPlaneToken = "X-Control-Plane-Token"
	headerOperatorID        = "X-Operator-Id"
	headerOperator          = "X-Operator"
	headerOperatorRole      = "X-Operator-Role"
	headerOperatorPerms     = "X-Operator-Permissions"
)

// Claims is the upstream-validated operator identity attached to the request.
// Role is informational; authorization uses the issued permissions.
type Claims struct {
	Subject     string
	Username    string
	Email       string
	Role        string
	Permissions []string
	// Source names the authority that validated this identity
	// ("control-plane" | "gateway"). Audit rows carry it so a log can
	// answer "who vouched for this operator?" during the migration.
	Source string
}

type claimsKey struct{}

func ActorFromContext(ctx context.Context) (Claims, bool) {
	c, ok := ctx.Value(claimsKey{}).(Claims)
	return c, ok
}

type AuthConfig struct {
	// ControlPlaneToken — shared secret with the Insight Control Plane.
	// When set, it is the ONLY accepted path and the Gateway is never
	// contacted.
	ControlPlaneToken string
	// IdentityURL — legacy Gateway introspection endpoint. Used only
	// when ControlPlaneToken is empty.
	IdentityURL string
	Client      *http.Client
}

type gatewayIdentityResponse struct {
	Operator struct {
		ID          string   `json:"id"`
		Username    string   `json:"username"`
		Email       string   `json:"email"`
		Role        string   `json:"role"`
		Permissions []string `json:"permissions"`
	} `json:"operator"`
}

func RequireAuth(cfg AuthConfig, next http.Handler) http.Handler {
	controlPlaneToken := strings.TrimSpace(cfg.ControlPlaneToken)
	identityURL := strings.TrimSpace(cfg.IdentityURL)
	client := cfg.Client
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var identity Claims
		var ok bool
		switch {
		case controlPlaneToken != "":
			identity, ok = authenticateControlPlane(w, r, controlPlaneToken)
		case identityURL != "":
			identity, ok = authenticateGateway(w, r, client, identityURL)
		default:
			// Fail closed, and say which knob unlocks it. "admin api
			// locked" alone sent people looking for a bug.
			authError(w, http.StatusServiceUnavailable,
				"admin api locked: set NEXUS_CONTROL_PLANE_TOKEN "+
					"(or the legacy NEXUS_GATEWAY_IDENTITY_URL)")
			return
		}
		if !ok {
			return // the helper already wrote the response.
		}
		required := requiredPermission(r)
		if !hasPermission(identity.Permissions, required) {
			authError(w, http.StatusForbidden, "permission required: "+required)
			return
		}
		next.ServeHTTP(w, r.WithContext(
			context.WithValue(r.Context(), claimsKey{}, identity)))
	})
}

// authenticateControlPlane verifies the service-to-service secret and takes
// the operator from the headers the Control Plane forwards.
//
// It does NOT re-validate the operator anywhere. The Control Plane already
// authenticated the person; asking a second authority to confirm is what
// produced 401 on every call once identity moved off the Gateway.
func authenticateControlPlane(
	w http.ResponseWriter, r *http.Request, expected string,
) (Claims, bool) {
	got := r.Header.Get(headerControlPlaneToken)
	// Constant-time: a plain == returns on the first differing byte, and
	// the timing difference leaks the token one byte at a time.
	if got == "" || subtle.ConstantTimeCompare([]byte(got), []byte(expected)) != 1 {
		authError(w, http.StatusUnauthorized, "invalid_control_plane_token")
		return Claims{}, false
	}
	permissions := parsePermissions(r.Header.Get(headerOperatorPerms))
	if len(permissions) == 0 {
		// Fail closed. Deriving permissions from the role here would fork
		// the RBAC table the Control Plane owns, and defaulting to "allow"
		// would make a forgotten header silently grant everything.
		authError(w, http.StatusForbidden,
			"control plane sent no "+headerOperatorPerms)
		return Claims{}, false
	}
	username := strings.TrimSpace(r.Header.Get(headerOperator))
	id := strings.TrimSpace(r.Header.Get(headerOperatorID))
	subject := username
	if subject == "" {
		subject = id
	}
	if subject == "" {
		// An audit row without an actor is not an audit row.
		authError(w, http.StatusForbidden,
			"control plane sent no operator identity")
		return Claims{}, false
	}
	return Claims{
		Subject:     subject,
		Username:    username,
		Role:        strings.TrimSpace(r.Header.Get(headerOperatorRole)),
		Permissions: permissions,
		Source:      "control-plane",
	}, true
}

// authenticateGateway is the legacy path: introspect the opaque session
// against the Gateway. Reached only when no Control Plane token is set.
func authenticateGateway(
	w http.ResponseWriter, r *http.Request, client *http.Client, identityURL string,
) (Claims, bool) {
	token := bearerToken(r.Header.Get("Authorization"))
	if token == "" {
		authError(w, http.StatusUnauthorized, "operator session required")
		return Claims{}, false
	}
	identity, status, err := resolveGatewayIdentity(r.Context(), client, identityURL, token)
	if err != nil {
		if status == http.StatusUnauthorized || status == http.StatusForbidden {
			authError(w, http.StatusUnauthorized, "invalid operator session")
			return Claims{}, false
		}
		authError(w, http.StatusServiceUnavailable, "Gateway identity unavailable")
		return Claims{}, false
	}
	identity.Source = "gateway"
	return identity, true
}

// parsePermissions splits the comma-separated header, dropping blanks so a
// trailing comma cannot become an empty permission that matches nothing.
func parsePermissions(raw string) []string {
	out := make([]string, 0, 4)
	for _, part := range strings.Split(raw, ",") {
		if p := strings.TrimSpace(part); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func resolveGatewayIdentity(
	ctx context.Context,
	client *http.Client,
	identityURL string,
	token string,
) (Claims, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, identityURL, nil)
	if err != nil {
		return Claims{}, 0, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	res, err := client.Do(req)
	if err != nil {
		return Claims{}, 0, err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return Claims{}, res.StatusCode, errors.New("Gateway rejected operator session")
	}
	var body gatewayIdentityResponse
	if err := json.NewDecoder(res.Body).Decode(&body); err != nil {
		return Claims{}, res.StatusCode, fmt.Errorf("decode Gateway identity: %w", err)
	}
	if body.Operator.ID == "" || len(body.Operator.Permissions) == 0 {
		return Claims{}, res.StatusCode, errors.New("Gateway returned incomplete identity")
	}
	subject := body.Operator.Email
	if subject == "" {
		subject = body.Operator.Username
	}
	if subject == "" {
		subject = body.Operator.ID
	}
	return Claims{
		Subject:     subject,
		Username:    body.Operator.Username,
		Email:       body.Operator.Email,
		Role:        body.Operator.Role,
		Permissions: append([]string(nil), body.Operator.Permissions...),
	}, res.StatusCode, nil
}

func requiredPermission(r *http.Request) string {
	if r.Method == http.MethodGet || r.Method == http.MethodHead {
		return permissionConsoleAccess
	}
	if r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/replay") {
		return permissionDLQReplay
	}
	return permissionConfigWrite
}

func hasPermission(permissions []string, required string) bool {
	for _, permission := range permissions {
		if permission == required {
			return true
		}
	}
	return false
}

func bearerToken(raw string) string {
	if len(raw) < 8 || !strings.EqualFold(raw[:7], "Bearer ") {
		return ""
	}
	return strings.TrimSpace(raw[7:])
}

func authError(w http.ResponseWriter, code int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
