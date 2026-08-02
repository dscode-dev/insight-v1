// Package llm — the provider contract (Sprint 4 Part 1).
//
// Application code (router, publisher) depends ONLY on this
// interface; concrete provider implementations (OpenAI, Anthropic,
// Gemini) live under internal/adapters/llm. No
// provider-specific logic exists outside adapters.
package llm

import (
	"context"
	"errors"
	"time"
)

var (
	// ErrUnavailable — the provider cannot serve right now (no key
	// configured, daemon down, network failure). The router treats
	// this as "skip + try next".
	ErrUnavailable = errors.New("llm: provider unavailable")
	// ErrMalformedOutput — the provider answered but the output failed
	// the caller's parse validation. Counts as a provider failure for
	// failover purposes.
	ErrMalformedOutput = errors.New("llm: malformed output")
)

// GenerateRequest is provider-agnostic. The prompt builder produces
// it; adapters translate to their wire formats.
type GenerateRequest struct {
	// System — the persona/system context.
	System string
	// Prompt — the user-turn content.
	Prompt string
	// MaxTokens — output budget. Adapters map to their own knob.
	MaxTokens int
	// Temperature — kept LOW for publication content (determinism
	// bias); adapters clamp to their valid ranges.
	Temperature float64
}

// GenerateResponse is the normalized provider answer.
type GenerateResponse struct {
	Text    string
	Model   string
	Latency time.Duration
}

// ProviderCapability describes behavior implemented by an adapter, rather
// than every feature offered by the upstream provider.
type ProviderCapability struct {
	Reasoning        bool
	ToolUse          bool
	StructuredOutput bool
	Streaming        bool
}

// Provider is the contract every LLM adapter implements.
type Provider interface {
	Name() string
	Capabilities() ProviderCapability
	Health(ctx context.Context) error
	Generate(ctx context.Context, req GenerateRequest) (*GenerateResponse, error)
}
