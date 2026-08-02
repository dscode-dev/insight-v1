// Gemini adapter — Sprint 4 Part 3 (private fallback, OPTIONAL).
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

type GeminiProvider struct {
	apiKey  string
	baseURL string
	model   string
	client  *http.Client
}

func NewGemini(apiKey, baseURL, model string, timeout time.Duration) *GeminiProvider {
	if baseURL == "" {
		baseURL = "https://generativelanguage.googleapis.com"
	}
	if model == "" {
		model = "gemini-2.5-flash"
	}
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &GeminiProvider{
		apiKey:  apiKey,
		baseURL: strings.TrimRight(baseURL, "/"),
		model:   model,
		client:  &http.Client{Timeout: timeout},
	}
}

func (p *GeminiProvider) Name() string { return "gemini" }

func (p *GeminiProvider) Capabilities() portllm.ProviderCapability {
	return portllm.ProviderCapability{
		Reasoning:        true,
		StructuredOutput: true,
	}
}

func (p *GeminiProvider) Health(ctx context.Context) error {
	if p.apiKey == "" {
		return fmt.Errorf("%w: no api key configured", portllm.ErrUnavailable)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		p.baseURL+"/v1beta/models/"+p.model+"?key="+p.apiKey, nil)
	if err != nil {
		return err
	}
	resp, err := p.client.Do(req)
	if err != nil {
		return fmt.Errorf("%w: %v", portllm.ErrUnavailable, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("%w: gemini status %d", portllm.ErrUnavailable, resp.StatusCode)
	}
	return nil
}

func (p *GeminiProvider) Generate(
	ctx context.Context, req portllm.GenerateRequest,
) (*portllm.GenerateResponse, error) {
	if p.apiKey == "" {
		return nil, fmt.Errorf("%w: no api key configured", portllm.ErrUnavailable)
	}
	body, err := json.Marshal(map[string]any{
		"system_instruction": map[string]any{
			"parts": []map[string]string{{"text": req.System}},
		},
		"contents": []map[string]any{{
			"role":  "user",
			"parts": []map[string]string{{"text": req.Prompt}},
		}},
		"generationConfig": map[string]any{
			"maxOutputTokens":  req.MaxTokens,
			"temperature":      req.Temperature,
			"responseMimeType": "application/json",
		},
	})
	if err != nil {
		return nil, err
	}
	started := time.Now()
	url := fmt.Sprintf("%s/v1beta/models/%s:generateContent?key=%s",
		p.baseURL, p.model, p.apiKey)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url,
		bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	resp, err := p.client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", portllm.ErrUnavailable, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("%w: gemini %d: %s", portllm.ErrUnavailable,
			resp.StatusCode, string(raw))
	}
	var out struct {
		Candidates []struct {
			Content struct {
				Parts []struct {
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"content"`
		} `json:"candidates"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil ||
		len(out.Candidates) == 0 || len(out.Candidates[0].Content.Parts) == 0 {
		return nil, fmt.Errorf("%w: empty/undecodable candidates", portllm.ErrMalformedOutput)
	}
	return &portllm.GenerateResponse{
		Text:    out.Candidates[0].Content.Parts[0].Text,
		Model:   p.model,
		Latency: time.Since(started),
	}, nil
}
