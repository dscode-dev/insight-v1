// Gateway-backed authentication for the Nexus administrative API.
//
// Nexus does not mint or verify operator credentials, own sessions, or define
// roles. It forwards the opaque operator session to Insight Gateway's
// /v1/operator/auth/me endpoint and consumes the validated identity and
// permissions returned by the platform identity authority.
package httpapi

import (
	"context"
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

// Claims is the Gateway-validated operator identity attached to the request.
// Role is informational; authorization uses Gateway-issued permissions.
type Claims struct {
	Subject     string
	Username    string
	Email       string
	Role        string
	Permissions []string
}

type claimsKey struct{}

func ActorFromContext(ctx context.Context) (Claims, bool) {
	c, ok := ctx.Value(claimsKey{}).(Claims)
	return c, ok
}

type AuthConfig struct {
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
	identityURL := strings.TrimSpace(cfg.IdentityURL)
	client := cfg.Client
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if identityURL == "" {
			authError(w, http.StatusServiceUnavailable,
				"admin api locked: Gateway identity endpoint not configured")
			return
		}
		token := bearerToken(r.Header.Get("Authorization"))
		if token == "" {
			authError(w, http.StatusUnauthorized, "operator session required")
			return
		}
		identity, status, err := resolveGatewayIdentity(
			r.Context(), client, identityURL, token)
		if err != nil {
			if status == http.StatusUnauthorized || status == http.StatusForbidden {
				authError(w, http.StatusUnauthorized, "invalid operator session")
				return
			}
			authError(w, http.StatusServiceUnavailable, "Gateway identity unavailable")
			return
		}
		required := requiredPermission(r)
		if !hasPermission(identity.Permissions, required) {
			authError(w, http.StatusForbidden,
				"Gateway permission required: "+required)
			return
		}
		next.ServeHTTP(w, r.WithContext(
			context.WithValue(r.Context(), claimsKey{}, identity)))
	})
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
