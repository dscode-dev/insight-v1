// Anthropic (Claude) adapter — Sprint 4 Part 3 (private fallback,
// OPTIONAL). No API key → permanently unavailable; never a startup
// failure.
package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	portllm "github.com/konoha-labs/insight-nexus/internal/ports/llm"
)

type AnthropicProvider struct {
	apiKey  string
	baseURL string
	model   string
	client  *http.Client
}

func NewAnthropic(apiKey, baseURL, model string, timeout time.Duration) *AnthropicProvider {
	if baseURL == "" {
		baseURL = "https://api.anthropic.com"
	}
	if model == "" {
		model = "claude-haiku-4-5-20251001"
	}
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &AnthropicProvider{
		apiKey:  apiKey,
		baseURL: strings.TrimRight(baseURL, "/"),
		model:   model,
		client:  &http.Client{Timeout: timeout},
	}
}

func (p *AnthropicProvider) Name() string { return "claude" }

func (p *AnthropicProvider) Capabilities() portllm.ProviderCapability {
	return portllm.ProviderCapability{
		Reasoning: true,
	}
}

func (p *AnthropicProvider) Health(ctx context.Context) error {
	if p.apiKey == "" {
		return fmt.Errorf("%w: no api key configured", portllm.ErrUnavailable)
	}
	// Anthropic has no cheap health endpoint; the models list is the
	// lightest authenticated probe.
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		p.baseURL+"/v1/models?limit=1", nil)
	if err != nil {
		return err
	}
	req.Header.Set("x-api-key", p.apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")
	resp, err := p.client.Do(req)
	if err != nil {
		return fmt.Errorf("%w: %v", portllm.ErrUnavailable, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("%w: anthropic status %d", portllm.ErrUnavailable, resp.StatusCode)
	}
	return nil
}

func (p *AnthropicProvider) Generate(
	ctx context.Context, req portllm.GenerateRequest,
) (*portllm.GenerateResponse, error) {
	if p.apiKey == "" {
		return nil, fmt.Errorf("%w: no api key configured", portllm.ErrUnavailable)
	}
	body, err := json.Marshal(map[string]any{
		"model":       p.model,
		"system":      req.System,
		"max_tokens":  req.MaxTokens,
		"temperature": req.Temperature,
		"messages": []map[string]string{
			{"role": "user", "content": req.Prompt},
		},
	})
	if err != nil {
		return nil, err
	}
	started := time.Now()
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost,
		p.baseURL+"/v1/messages", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("x-api-key", p.apiKey)
	httpReq.Header.Set("anthropic-version", "2023-06-01")
	resp, err := p.client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", portllm.ErrUnavailable, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("%w: anthropic %d: %s", portllm.ErrUnavailable,
			resp.StatusCode, string(raw))
	}
	var out struct {
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
		Model string `json:"model"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil ||
		len(out.Content) == 0 {
		return nil, fmt.Errorf("%w: empty/undecodable content", portllm.ErrMalformedOutput)
	}
	return &portllm.GenerateResponse{
		Text:    out.Content[0].Text,
		Model:   out.Model,
		Latency: time.Since(started),
	}, nil
}
