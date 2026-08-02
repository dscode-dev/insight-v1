// LLM Router — Sprint 4 Part 5.
//
// Provider order is supplied by the composition root:
//
//	claude → gpt → gemini
//
// Rules: skip offline providers; skip degraded providers while a
// healthy alternative remains; fail over automatically; record the
// full fallback chain. The caller's parse validation runs per
// attempt — malformed output counts as a provider failure and the
// chain continues.
package llmrouter

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/rs/zerolog"

	portllm "github.com/konoha-labs/insight-nexus/internal/ports/llm"
)

// ErrAllProvidersFailed — every eligible provider failed. The
// publisher MUST create a publication ticket (never auto-publish).
var ErrAllProvidersFailed = errors.New("llmrouter: all providers failed")

// RouterMetrics — observability seam.
type RouterMetrics interface {
	LLMLatency(provider string, seconds float64)
	Fallback(from, to string)
}

// RouteResult — the explainability record of one generation.
type RouteResult struct {
	Provider     string
	Model        string
	FallbackUsed bool
	// Chain — every provider attempted, in order
	// ("claude:offline", "gpt:failed", "gemini:ok").
	Chain []string
}

type Router struct {
	providers []portllm.Provider // priority order
	health    *HealthManager
	metrics   RouterMetrics
	logger    zerolog.Logger
}

func NewRouter(
	providers []portllm.Provider,
	health *HealthManager,
	metrics RouterMetrics,
	logger zerolog.Logger,
) *Router {
	return &Router{
		providers: providers,
		health:    health,
		metrics:   metrics,
		logger:    logger,
	}
}

// Generate runs the failover chain. `parse` validates each provider's
// output (nil = accept anything); a parse failure is a provider
// failure and the chain continues.
func (r *Router) Generate(
	ctx context.Context,
	req portllm.GenerateRequest,
	parse func(text string) error,
) (*portllm.GenerateResponse, RouteResult, error) {
	result := RouteResult{}
	healthyExists := false
	for _, p := range r.providers {
		if r.health.StatusOf(p.Name()) == StatusHealthy {
			healthyExists = true
			break
		}
	}

	attempted := 0
	for _, p := range r.providers {
		status := r.health.StatusOf(p.Name())
		if status == StatusOffline {
			result.Chain = append(result.Chain, p.Name()+":offline")
			continue
		}
		if status == StatusDegraded && healthyExists {
			result.Chain = append(result.Chain, p.Name()+":degraded-skipped")
			continue
		}
		attempted++
		started := time.Now()
		resp, err := p.Generate(ctx, req)
		if err == nil && parse != nil {
			if perr := parse(resp.Text); perr != nil {
				err = fmt.Errorf("%w: %v", portllm.ErrMalformedOutput, perr)
			}
		}
		if r.metrics != nil {
			r.metrics.LLMLatency(p.Name(), time.Since(started).Seconds())
		}
		if err != nil {
			result.Chain = append(result.Chain, p.Name()+":failed")
			r.health.ReportGenerationFailure(p.Name(), err)
			r.logger.Warn().
				Str("provider", p.Name()).
				Err(err).
				Msg("llm_generation_failed_failing_over")
			if r.metrics != nil {
				r.metrics.Fallback(p.Name(), "next")
			}
			continue
		}
		result.Chain = append(result.Chain, p.Name()+":ok")
		result.Provider = p.Name()
		result.Model = resp.Model
		result.FallbackUsed = attempted > 1 || len(result.Chain) > 1
		return resp, result, nil
	}
	return nil, result, ErrAllProvidersFailed
}
