// Package httpapi — HTTP surface for the Hub.
//
// Sprint 1 exposed:
//
//	GET /healthz
//	GET /readyz
//	GET /metrics
//
// Sprint 2 adds:
//
//	GET /v1/providers/status   per-provider operational snapshot
//
// Ingest endpoints are still NOT exposed — provider adapters call
// the orchestrator in-process. Cross-service HTTP ingest is Sprint 3+.
package httpapi

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"

	"github.com/konoha-labs/insight-runtime-go/pkg/health"
	"github.com/konoha-labs/insight-runtime-go/pkg/middleware"
)

// RoutesConfig bundles every dependency the route surface needs.
// main.go fills it at the composition root.
type RoutesConfig struct {
	Health          *health.Checker
	MetricsHandler  http.Handler // may be nil
	ProvidersStatus http.Handler // may be nil when no adapters registered
	SchedulerStatus http.Handler // Sprint 3: nil before scheduler boots
	// Sprint 5.1 — DLQ admin handlers. All three may be nil when the
	// composition root wires the NoopDLQ (no persistent store).
	DLQList   http.Handler
	DLQGet    http.Handler
	DLQReplay http.Handler
	DLQToken  string
}

// MaxBodyBytes — Sprint 6 default body-size limit. POST /v1/dlq/{id}/replay
// is the only mutating route and carries no body; the limit is conservative.
const MaxBodyBytes = 64 * 1024

func Routes(cfg RoutesConfig) http.Handler {
	mux := http.NewServeMux()
	mux.Handle("/healthz", cfg.Health.Liveness())
	mux.Handle("/readyz", cfg.Health.Readiness())
	if cfg.MetricsHandler != nil {
		mux.Handle("/metrics", cfg.MetricsHandler)
	}
	if cfg.ProvidersStatus != nil {
		mux.Handle("/v1/providers/status", cfg.ProvidersStatus)
	}
	if cfg.SchedulerStatus != nil {
		mux.Handle("/v1/scheduler/status", cfg.SchedulerStatus)
	}
	if cfg.DLQList != nil {
		mux.Handle("/v1/dlq", requireOpsToken(cfg.DLQToken, cfg.DLQList))
	}
	if cfg.DLQReplay != nil {
		mux.HandleFunc("/v1/dlq/", func(w http.ResponseWriter, r *http.Request) {
			if r.Method == http.MethodPost &&
				len(r.URL.Path) > len("/v1/dlq/") &&
				r.URL.Path[len(r.URL.Path)-len("/replay"):] == "/replay" {
				requireOpsToken(cfg.DLQToken, cfg.DLQReplay).ServeHTTP(w, r)
				return
			}
			if cfg.DLQGet != nil {
				requireOpsToken(cfg.DLQToken, cfg.DLQGet).ServeHTTP(w, r)
				return
			}
			http.NotFound(w, r)
		})
	}

	// Sprint 6 — middleware chain. Order matters:
	//   RequestID first   → every downstream layer sees the correlation id
	//   Recovery next     → panics become 500s with the id in logs
	//   SecurityHeaders   → safe to add headers before body is written
	//   BodyLimit last    → wraps the actual request body reader
	return middleware.RequestID()(
		middleware.Recovery()(
			middleware.SecurityHeaders(middleware.SecurityHeadersConfig{})(
				middleware.BodyLimit(MaxBodyBytes)(mux),
			),
		),
	)
}

func requireOpsToken(token string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if token == "" {
			writeOpsError(w, http.StatusServiceUnavailable, "sport_hub_ops_disabled")
			return
		}
		got := r.Header.Get("X-Ops-Token")
		if got == "" || subtle.ConstantTimeCompare([]byte(got), []byte(token)) != 1 {
			writeOpsError(w, http.StatusUnauthorized, "invalid_ops_token")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func writeOpsError(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}
