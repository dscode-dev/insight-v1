// Package providers contains Gateway-owned phone verification providers.
//
// Providers prove phone ownership only. They do not create Insight users,
// issue Insight tokens, or own sessions. The application/auth service consumes
// the domain PhoneAuthProvider port and then resolves the verified phone
// through the existing Insight identity/session path.
package providers

import (
	"net/http"
	"strings"
	"time"

	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

type FactoryConfig struct {
	Provider       string
	SupabaseURL    string
	SupabaseKey    string
	RequestTimeout time.Duration
}

// NewFromConfig returns nil for the local Gateway OTP provider. That preserves
// the existing first-party OTP challenge flow as the default/rollback path.
func NewFromConfig(cfg FactoryConfig) domauth.PhoneAuthProvider {
	switch strings.ToLower(strings.TrimSpace(cfg.Provider)) {
	case "firebase":
		return FirebaseProvider{}
	case "supabase":
		return NewSupabaseProvider(SupabaseConfig{
			URL:     cfg.SupabaseURL,
			AnonKey: cfg.SupabaseKey,
			HTTP:    httpClient(cfg.RequestTimeout),
		})
	default:
		return nil
	}
}

func httpClient(timeout time.Duration) *http.Client {
	if timeout <= 0 {
		timeout = 6 * time.Second
	}
	return &http.Client{Timeout: timeout}
}
