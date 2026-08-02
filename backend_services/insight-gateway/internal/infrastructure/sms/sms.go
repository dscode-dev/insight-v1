// Package sms implements the auth.SmsProvider port.
//
// 3 providers ship in V1:
//   - NullProvider    — logs to stderr (lab + tests)
//   - ZenviaProvider  — production default (BR carriers)
//   - TwilioProvider  — sandbox + non-BR fallback
//
// The Factory picks one based on the SMS_PROVIDER env value, with a
// graceful fallback to NullProvider when required credentials for
// the chosen provider are missing (logged at WARN). This means a
// misconfigured prod boot doesn't crash — it ships SMS-less so the
// app stays up while ops investigates.
package sms

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/rs/zerolog/log"

	"github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

// errProviderRejected is the umbrella error for upstream non-2xx.
// Application layer maps this to auth.ErrOtpDispatch.
var errProviderRejected = errors.New("sms_provider_rejected")

// ---- Null ----

// NullProvider records that a local-only SMS dispatch would have happened and
// returns success. It never logs phone numbers or OTP bodies.
type NullProvider struct{}

func (NullProvider) Name() string { return "null" }

func (NullProvider) SendOtp(_ context.Context, _ string, body string) (string, error) {
	log.Warn().Int("message_len", len(body)).Msg("sms_null_provider_dispatch")
	return "", nil
}

// ---- Zenvia ----
// https://zenvia.github.io/zenvia-openapi-spec/v2/

type ZenviaProvider struct {
	APIToken string
	SenderID string
	BaseURL  string // override only for tests; defaults to public API
	HTTP     *http.Client
}

func (ZenviaProvider) Name() string { return "zenvia" }

func (p ZenviaProvider) SendOtp(ctx context.Context, phoneE164, body string) (string, error) {
	base := p.BaseURL
	if base == "" {
		base = "https://api.zenvia.com"
	}
	payload, _ := json.Marshal(map[string]interface{}{
		"from": p.SenderID,
		"to":   phoneE164,
		"contents": []map[string]string{
			{"type": "text", "text": body},
		},
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		base+"/v2/channels/sms/messages", strings.NewReader(string(payload)))
	if err != nil {
		return "", fmt.Errorf("zenvia: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-TOKEN", p.APIToken)

	resp, err := p.HTTP.Do(req)
	if err != nil {
		return "", fmt.Errorf("zenvia: transport: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("%w: status=%d", errProviderRejected, resp.StatusCode)
	}
	var out map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", nil // 2xx but unparseable body — treat as success without id
	}
	id, _ := out["id"].(string)
	return id, nil
}

// ---- Twilio ----
// https://www.twilio.com/docs/sms/api/message-resource

type TwilioProvider struct {
	AccountSID string
	AuthToken  string
	From       string // E.164 number OR Messaging Service SID (starts with "MG")
	BaseURL    string
	HTTP       *http.Client
}

func (TwilioProvider) Name() string { return "twilio" }

func (p TwilioProvider) SendOtp(ctx context.Context, phoneE164, body string) (string, error) {
	base := p.BaseURL
	if base == "" {
		base = "https://api.twilio.com"
	}

	form := url.Values{}
	if strings.HasPrefix(p.From, "MG") {
		form.Set("MessagingServiceSid", p.From)
	} else {
		form.Set("From", p.From)
	}
	form.Set("To", phoneE164)
	form.Set("Body", body)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		fmt.Sprintf("%s/2010-04-01/Accounts/%s/Messages.json", base, p.AccountSID),
		strings.NewReader(form.Encode()))
	if err != nil {
		return "", fmt.Errorf("twilio: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.SetBasicAuth(p.AccountSID, p.AuthToken)

	resp, err := p.HTTP.Do(req)
	if err != nil {
		return "", fmt.Errorf("twilio: transport: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("%w: status=%d", errProviderRejected, resp.StatusCode)
	}
	var out map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", nil
	}
	sid, _ := out["sid"].(string)
	return sid, nil
}

// ---- Factory ----

type FactoryConfig struct {
	Provider       string // "null" | "zenvia" | "twilio"
	ZenviaToken    string
	ZenviaSender   string
	TwilioSID      string
	TwilioToken    string
	TwilioFrom     string
	RequestTimeout time.Duration
}

// NewFromConfig picks a provider, gracefully falling back to Null when
// the chosen provider's credentials are incomplete. Always returns a
// usable SmsProvider — never errors.
func NewFromConfig(cfg FactoryConfig) auth.SmsProvider {
	httpClient := &http.Client{Timeout: cfg.RequestTimeout}
	if httpClient.Timeout == 0 {
		httpClient.Timeout = 6 * time.Second
	}

	switch strings.ToLower(strings.TrimSpace(cfg.Provider)) {
	case "zenvia":
		if cfg.ZenviaToken == "" {
			log.Warn().Msg("sms_provider_zenvia_missing_token_falling_back_to_null")
			return NullProvider{}
		}
		sender := cfg.ZenviaSender
		if sender == "" {
			sender = "Insight"
		}
		return ZenviaProvider{
			APIToken: cfg.ZenviaToken,
			SenderID: sender,
			HTTP:     httpClient,
		}
	case "twilio":
		if cfg.TwilioSID == "" || cfg.TwilioToken == "" || cfg.TwilioFrom == "" {
			log.Warn().Msg("sms_provider_twilio_missing_creds_falling_back_to_null")
			return NullProvider{}
		}
		return TwilioProvider{
			AccountSID: cfg.TwilioSID,
			AuthToken:  cfg.TwilioToken,
			From:       cfg.TwilioFrom,
			HTTP:       httpClient,
		}
	default:
		return NullProvider{}
	}
}
