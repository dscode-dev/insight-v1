// ProviderHealthManager — Sprint 4 Part 4.
//
// Tracks every provider's routing eligibility:
//
//	healthy  — last check passed and no recent generation failures
//	degraded — recovering (one pass after failure) OR recent
//	           generation failure despite a passing health check
//	offline  — last health check failed
//
// A periodic loop re-checks all providers; the router also reports
// generation failures so a provider that "looks healthy" but fails
// real requests degrades immediately.
package llmrouter

import (
	"context"
	"sync"
	"time"

	"github.com/rs/zerolog"

	portllm "github.com/konoha-labs/insight-nexus/internal/ports/llm"
)

type Status string

const (
	StatusHealthy  Status = "healthy"
	StatusDegraded Status = "degraded"
	StatusOffline  Status = "offline"
)

// HealthMetrics — observability seam (nexus_provider_health gauge).
type HealthMetrics interface {
	ProviderHealth(provider string, status Status)
}

type providerState struct {
	status       Status
	lastChecked  time.Time
	lastError    string
	consecutivOK int
}

type HealthManager struct {
	mu        sync.RWMutex
	providers []portllm.Provider
	states    map[string]*providerState
	interval  time.Duration
	timeout   time.Duration
	metrics   HealthMetrics
	logger    zerolog.Logger
}

func NewHealthManager(
	providers []portllm.Provider,
	interval time.Duration,
	metrics HealthMetrics,
	logger zerolog.Logger,
) *HealthManager {
	if interval <= 0 {
		interval = 30 * time.Second
	}
	states := make(map[string]*providerState, len(providers))
	for _, p := range providers {
		// Unknown until first check — treated as offline so the
		// router never routes to an unverified provider.
		states[p.Name()] = &providerState{status: StatusOffline}
	}
	return &HealthManager{
		providers: providers,
		states:    states,
		interval:  interval,
		timeout:   10 * time.Second,
		metrics:   metrics,
		logger:    logger,
	}
}

// Run starts the periodic check loop (call in a goroutine). One
// immediate pass on start so the router is usable right away.
func (h *HealthManager) Run(ctx context.Context) {
	h.CheckAll(ctx)
	ticker := time.NewTicker(h.interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			h.CheckAll(ctx)
		}
	}
}

// CheckAll performs one health pass over every provider.
func (h *HealthManager) CheckAll(ctx context.Context) {
	for _, p := range h.providers {
		checkCtx, cancel := context.WithTimeout(ctx, h.timeout)
		err := p.Health(checkCtx)
		cancel()
		h.record(p.Name(), err)
	}
}

func (h *HealthManager) record(name string, err error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	st := h.states[name]
	if st == nil {
		st = &providerState{}
		h.states[name] = st
	}
	st.lastChecked = time.Now().UTC()
	previous := st.status
	if err != nil {
		st.status = StatusOffline
		st.lastError = err.Error()
		st.consecutivOK = 0
	} else {
		st.consecutivOK++
		st.lastError = ""
		// One pass after a failure = degraded; two consecutive
		// passes = healthy. Smooths flapping providers.
		if st.consecutivOK >= 2 {
			st.status = StatusHealthy
		} else {
			st.status = StatusDegraded
		}
	}
	if h.metrics != nil {
		h.metrics.ProviderHealth(name, st.status)
	}
	if previous != st.status {
		h.logger.Info().
			Str("provider", name).
			Str("from", string(previous)).
			Str("to", string(st.status)).
			Str("error", st.lastError).
			Msg("llm_provider_status_changed")
	}
}

// ReportGenerationFailure degrades a provider after a real-request
// failure (its next health pass can recover it).
func (h *HealthManager) ReportGenerationFailure(name string, err error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	st := h.states[name]
	if st == nil {
		return
	}
	st.consecutivOK = 0
	if st.status == StatusHealthy {
		st.status = StatusDegraded
		st.lastError = err.Error()
		if h.metrics != nil {
			h.metrics.ProviderHealth(name, st.status)
		}
	}
}

// StatusOf returns the provider's routing status.
func (h *HealthManager) StatusOf(name string) Status {
	h.mu.RLock()
	defer h.mu.RUnlock()
	if st := h.states[name]; st != nil {
		return st.status
	}
	return StatusOffline
}

// Snapshot — the admin API view.
type Snapshot struct {
	Provider    string    `json:"provider"`
	Status      Status    `json:"status"`
	LastChecked time.Time `json:"last_checked"`
	LastError   string    `json:"last_error,omitempty"`
}

func (h *HealthManager) Snapshots() []Snapshot {
	h.mu.RLock()
	defer h.mu.RUnlock()
	out := make([]Snapshot, 0, len(h.providers))
	for _, p := range h.providers {
		st := h.states[p.Name()]
		out = append(out, Snapshot{
			Provider:    p.Name(),
			Status:      st.status,
			LastChecked: st.lastChecked,
			LastError:   st.lastError,
		})
	}
	return out
}
