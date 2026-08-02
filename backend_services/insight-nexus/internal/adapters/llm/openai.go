// OpenAI adapter — Sprint 4 Part 3 (private fallback, OPTIONAL).
// No API key → permanently unavailable; never a startup failure.
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

type OpenAIProvider struct {
	apiKey  string
	baseURL string
	model   string
	client  *http.Client
}

func NewOpenAI(apiKey, baseURL, model string, timeout time.Duration) *OpenAIProvider {
	if baseURL == "" {
		baseURL = "https://api.openai.com"
	}
	if model == "" {
		model = "gpt-4o-mini"
	}
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &OpenAIProvider{
		apiKey:  apiKey,
		baseURL: strings.TrimRight(baseURL, "/"),
		model:   model,
		client:  &http.Client{Timeout: timeout},
	}
}

func (p *OpenAIProvider) Name() string { return "gpt" }

func (p *OpenAIProvider) Capabilities() portllm.ProviderCapability {
	return portllm.ProviderCapability{
		Reasoning:        true,
		StructuredOutput: true,
	}
}

func (p *OpenAIProvider) Health(ctx context.Context) error {
	if p.apiKey == "" {
		return fmt.Errorf("%w: no api key configured", portllm.ErrUnavailable)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		p.baseURL+"/v1/models/"+p.model, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+p.apiKey)
	resp, err := p.client.Do(req)
	if err != nil {
		return fmt.Errorf("%w: %v", portllm.ErrUnavailable, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("%w: openai status %d", portllm.ErrUnavailable, resp.StatusCode)
	}
	return nil
}

func (p *OpenAIProvider) Generate(
	ctx context.Context, req portllm.GenerateRequest,
) (*portllm.GenerateResponse, error) {
	if p.apiKey == "" {
		return nil, fmt.Errorf("%w: no api key configured", portllm.ErrUnavailable)
	}
	body, err := json.Marshal(map[string]any{
		"model": p.model,
		"messages": []map[string]string{
			{"role": "system", "content": req.System},
			{"role": "user", "content": req.Prompt},
		},
		"max_tokens":      req.MaxTokens,
		"temperature":     req.Temperature,
		"response_format": map[string]string{"type": "json_object"},
	})
	if err != nil {
		return nil, err
	}
	started := time.Now()
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost,
		p.baseURL+"/v1/chat/completions", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+p.apiKey)
	resp, err := p.client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", portllm.ErrUnavailable, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("%w: openai %d: %s", portllm.ErrUnavailable,
			resp.StatusCode, string(raw))
	}
	var out struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Model string `json:"model"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil ||
		len(out.Choices) == 0 {
		return nil, fmt.Errorf("%w: empty/undecodable choices", portllm.ErrMalformedOutput)
	}
	return &portllm.GenerateResponse{
		Text:    out.Choices[0].Message.Content,
		Model:   out.Model,
		Latency: time.Since(started),
	}, nil
}
