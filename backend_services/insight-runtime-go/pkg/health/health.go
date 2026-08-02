// Package health provides the two standard probes Kubernetes wires:
//
//	GET /healthz   — liveness  (cheap, no downstream calls)
//	GET /readyz    — readiness (checks DB + Redis + downstream gRPC)
//
// A service:
//
//	checker := health.New()
//	checker.AddReadiness("postgres", db.PingContext)
//	checker.AddReadiness("redis", redisClient.Ping)
//
//	mux.Handle("/healthz", checker.Liveness())
//	mux.Handle("/readyz", checker.Readiness())
//
// Liveness only fails if the process is so broken it cannot serve the
// handler. Readiness reports `200 OK` only when every registered probe
// returns nil within a 1-second budget.
package health

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"
	"time"
)

// ProbeFunc returns nil when the dependency is healthy.
type ProbeFunc func(context.Context) error

type entry struct {
	name string
	fn   ProbeFunc
}

type Checker struct {
	mu          sync.RWMutex
	probes      []entry
	probeBudget time.Duration
}

func New() *Checker {
	return &Checker{probeBudget: time.Second}
}

func (c *Checker) AddReadiness(name string, fn ProbeFunc) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.probes = append(c.probes, entry{name: name, fn: fn})
}

// Liveness always returns 200 unless the process is truly stuck.
// Kubernetes restarts the pod when this fails.
func (c *Checker) Liveness() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
}

// Readiness fans probes out concurrently with a 1-second budget. Any
// failing probe (or budget exceeded) returns 503 + a JSON summary of
// which dependencies are degraded.
func (c *Checker) Readiness() http.Handler {
	type result struct {
		Name  string `json:"name"`
		OK    bool   `json:"ok"`
		Error string `json:"error,omitempty"`
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c.mu.RLock()
		probes := append([]entry(nil), c.probes...)
		budget := c.probeBudget
		c.mu.RUnlock()

		ctx, cancel := context.WithTimeout(r.Context(), budget)
		defer cancel()

		results := make([]result, len(probes))
		var wg sync.WaitGroup
		for i, p := range probes {
			wg.Add(1)
			go func(i int, p entry) {
				defer wg.Done()
				if err := p.fn(ctx); err != nil {
					results[i] = result{Name: p.name, OK: false, Error: err.Error()}
					return
				}
				results[i] = result{Name: p.name, OK: true}
			}(i, p)
		}
		wg.Wait()

		ok := true
		for _, r := range results {
			if !r.OK {
				ok = false
				break
			}
		}
		w.Header().Set("Content-Type", "application/json")
		if !ok {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": map[bool]string{true: "ok", false: "degraded"}[ok],
			"probes": results,
		})
	})
}
