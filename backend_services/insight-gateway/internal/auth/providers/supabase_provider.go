package providers

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"

	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

type SupabaseConfig struct {
	URL     string
	AnonKey string
	HTTP    *http.Client
}

type SupabaseProvider struct {
	baseURL string
	anonKey string
	http    *http.Client
}

func NewSupabaseProvider(cfg SupabaseConfig) *SupabaseProvider {
	return &SupabaseProvider{
		baseURL: normalizeSupabaseURL(cfg.URL),
		anonKey: cfg.AnonKey,
		http:    cfg.HTTP,
	}
}

func (p *SupabaseProvider) Name() string { return "supabase" }

// SendCode uses Supabase GoTrue:
//
//	POST {SUPABASE_URL}/auth/v1/otp
//	{ "phone": "+5581999999999" }
func (p *SupabaseProvider) SendCode(ctx context.Context, phoneE164 string) (string, error) {
	if err := p.configured(); err != nil {
		return "", err
	}
	resp, err := p.do(ctx, http.MethodPost, "/auth/v1/otp", map[string]string{
		"phone": phoneE164,
	})
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return "", p.upstreamErr(resp)
	}
	return "", nil
}

// VerifyCode uses Supabase GoTrue:
//
//	POST {SUPABASE_URL}/auth/v1/verify
//	{ "phone": "+5581999999999", "token": "123456", "type": "sms" }
//
// The response may contain a Supabase user/session; Gateway intentionally
// discards it. Phone ownership is the only accepted signal.
func (p *SupabaseProvider) VerifyCode(ctx context.Context, phoneE164, code string) error {
	if err := p.configured(); err != nil {
		return err
	}
	resp, err := p.do(ctx, http.MethodPost, "/auth/v1/verify", map[string]string{
		"phone": phoneE164,
		"token": code,
		"type":  "sms",
	})
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return p.upstreamErr(resp)
	}
	return nil
}

func (p *SupabaseProvider) configured() error {
	if p.baseURL == "" || p.anonKey == "" || p.http == nil {
		return domauth.ErrPhoneProviderNotConfigured
	}
	return nil
}

func normalizeSupabaseURL(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme == "" || u.Host == "" {
		return strings.TrimRight(raw, "/")
	}
	u.Path = strings.TrimRight(u.Path, "/")
	if strings.HasSuffix(u.Path, "/rest/v1") {
		u.Path = strings.TrimSuffix(u.Path, "/rest/v1")
	}
	u.RawQuery = ""
	u.Fragment = ""
	return strings.TrimRight(u.String(), "/")
}

func (p *SupabaseProvider) do(ctx context.Context, method, path string, body any) (*http.Response, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("supabase: marshal request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, method, p.baseURL+path, bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("supabase: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("apikey", p.anonKey)
	req.Header.Set("Authorization", "Bearer "+p.anonKey)
	return p.http.Do(req)
}

func (p *SupabaseProvider) upstreamErr(resp *http.Response) error {
	if resp.StatusCode == http.StatusUnauthorized ||
		resp.StatusCode == http.StatusForbidden ||
		resp.StatusCode == http.StatusUnprocessableEntity ||
		resp.StatusCode == http.StatusTooManyRequests ||
		resp.StatusCode == http.StatusBadRequest {
		return fmt.Errorf("%w: status=%d", domauth.ErrPhoneProviderInvalid, resp.StatusCode)
	}
	return fmt.Errorf("supabase: status=%d", resp.StatusCode)
}
