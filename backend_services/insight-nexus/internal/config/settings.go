// Package config — typed Settings + env parser for Nexus.
package config

import (
	"fmt"
	"strings"

	rtconfig "github.com/konoha-labs/insight-runtime-go/pkg/config"
)

type Settings struct {
	Service string
	Version string

	HTTPAddr    string
	DatabaseURL string

	RedisAddr     string
	RedisPassword string
	RedisDB       int

	TrendStream   string
	ConsumerGroup string
	ConsumerName  string
	QueueMaxLen   int64

	QueueDepthPollSeconds int

	// Sprint 3.5 — pending recovery + DLQ.
	ClaimerEnabled       bool
	ClaimerMinIdleSec    int
	ClaimerIntervalSec   int
	ClaimerMaxDeliveries int
	DLQStream            string
	// GatewayIdentityURL is Insight Gateway's operator-session introspection
	// endpoint. Nexus owns no users, sessions, JWT secrets or RBAC.
	GatewayIdentityURL string

	// Sprint 3.5 — narrative lifecycle.
	ClusterExpireMinutes int

	// ---- Sprint 4 — publication engine ----
	PublisherEnabled bool
	SocialGrpcAddr   string

	// Private LLM providers — OPTIONAL: empty keys = provider offline,
	// never a startup failure.
	OpenAIKey       string
	OpenAIModel     string
	AnthropicKey    string
	AnthropicModel  string
	GeminiKey       string
	GeminiModel     string
	EnableOpenAI    bool
	EnableAnthropic bool
	EnableGemini    bool
	ProviderOrder   []string
	DefaultProvider string

	LLMHealthIntervalSec int
	LLMTimeoutSec        int

	// Anti-spam budgets (minutes / counts).
	SpamAgentCooldownMin   int
	SpamClusterCooldownMin int
	SpamTrendCooldownMin   int
	SpamMatchCooldownMin   int
	SpamHourlyLimit        int
	SpamDailyLimit         int

	LogLevel  string
	LogPretty bool
}

func Load() (*Settings, error) {
	s := &Settings{
		Service:     rtconfig.String("INSIGHT_SERVICE", "insight-nexus"),
		Version:     rtconfig.String("INSIGHT_VERSION", "dev"),
		HTTPAddr:    rtconfig.String("HTTP_ADDR", ":8090"),
		DatabaseURL: rtconfig.MustString("DATABASE_URL"),

		RedisAddr:     rtconfig.String("REDIS_ADDR", "localhost:6379"),
		RedisPassword: rtconfig.String("REDIS_PASSWORD", ""),

		TrendStream:   rtconfig.String("TREND_STREAM", "insight:stream:trends"),
		ConsumerGroup: rtconfig.String("NEXUS_CONSUMER_GROUP", "insight-nexus"),
		ConsumerName:  rtconfig.String("NEXUS_CONSUMER_NAME", "nexus-1"),

		LogLevel:  rtconfig.String("LOG_LEVEL", "info"),
		LogPretty: rtconfig.Bool("LOG_PRETTY", false),
	}
	var err error
	if s.RedisDB, err = rtconfig.Int("REDIS_DB", 0); err != nil {
		return nil, fmt.Errorf("REDIS_DB: %w", err)
	}
	maxLen, err := rtconfig.Int("NEXUS_QUEUE_MAX_LEN", 50_000)
	if err != nil {
		return nil, fmt.Errorf("NEXUS_QUEUE_MAX_LEN: %w", err)
	}
	s.QueueMaxLen = int64(maxLen)
	if s.QueueDepthPollSeconds, err = rtconfig.Int("NEXUS_QUEUE_DEPTH_POLL_SECONDS", 30); err != nil {
		return nil, fmt.Errorf("NEXUS_QUEUE_DEPTH_POLL_SECONDS: %w", err)
	}

	// Sprint 3.5 — claimer + lifecycle knobs.
	s.ClaimerEnabled = rtconfig.Bool("NEXUS_CLAIMER_ENABLED", true)
	if s.ClaimerMinIdleSec, err = rtconfig.Int("NEXUS_CLAIMER_MIN_IDLE", 30); err != nil {
		return nil, fmt.Errorf("NEXUS_CLAIMER_MIN_IDLE: %w", err)
	}
	if s.ClaimerIntervalSec, err = rtconfig.Int("NEXUS_CLAIMER_INTERVAL", 15); err != nil {
		return nil, fmt.Errorf("NEXUS_CLAIMER_INTERVAL: %w", err)
	}
	if s.ClaimerMaxDeliveries, err = rtconfig.Int("NEXUS_CLAIMER_MAX_DELIVERIES", 8); err != nil {
		return nil, fmt.Errorf("NEXUS_CLAIMER_MAX_DELIVERIES: %w", err)
	}
	s.DLQStream = rtconfig.String("NEXUS_DLQ_STREAM", "insight:dlq:nexus")
	s.GatewayIdentityURL = rtconfig.String("NEXUS_GATEWAY_IDENTITY_URL", "")

	// ---- Sprint 4 — publication engine ----
	s.PublisherEnabled = rtconfig.Bool("NEXUS_PUBLISHER_ENABLED", false)
	s.SocialGrpcAddr = rtconfig.String("NEXUS_SOCIAL_GRPC_ADDR", "")
	s.OpenAIKey = rtconfig.String("OPENAI_API_KEY", "")
	s.OpenAIModel = modelEnv("OPENAI_MODEL", "NEXUS_OPENAI_MODEL", "gpt-4o-mini")
	s.AnthropicKey = rtconfig.String("ANTHROPIC_API_KEY", "")
	s.AnthropicModel = modelEnv("ANTHROPIC_MODEL", "NEXUS_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
	s.GeminiKey = rtconfig.String("GEMINI_API_KEY", "")
	s.GeminiModel = modelEnv("GEMINI_MODEL", "NEXUS_GEMINI_MODEL", "gemini-2.5-flash")
	s.EnableOpenAI = rtconfig.Bool("NEXUS_ENABLE_OPENAI", false)
	s.EnableAnthropic = rtconfig.Bool("NEXUS_ENABLE_ANTHROPIC", false)
	s.EnableGemini = rtconfig.Bool("NEXUS_ENABLE_GEMINI", false)
	s.DefaultProvider = normalizeProvider(rtconfig.String("NEXUS_DEFAULT_PROVIDER", "anthropic"))
	s.ProviderOrder = providerOrder(
		rtconfig.String("NEXUS_PROVIDER_ORDER", "anthropic,openai,gemini"),
		s.DefaultProvider,
	)
	if s.LLMHealthIntervalSec, err = rtconfig.Int("NEXUS_LLM_HEALTH_INTERVAL", 30); err != nil {
		return nil, err
	}
	if s.LLMTimeoutSec, err = rtconfig.Int("NEXUS_LLM_TIMEOUT", 60); err != nil {
		return nil, err
	}
	if s.SpamAgentCooldownMin, err = rtconfig.Int("NEXUS_SPAM_AGENT_COOLDOWN_MIN", 5); err != nil {
		return nil, err
	}
	if s.SpamClusterCooldownMin, err = rtconfig.Int("NEXUS_SPAM_CLUSTER_COOLDOWN_MIN", 15); err != nil {
		return nil, err
	}
	if s.SpamTrendCooldownMin, err = rtconfig.Int("NEXUS_SPAM_TREND_COOLDOWN_MIN", 30); err != nil {
		return nil, err
	}
	if s.SpamMatchCooldownMin, err = rtconfig.Int("NEXUS_SPAM_MATCH_COOLDOWN_MIN", 10); err != nil {
		return nil, err
	}
	if s.SpamHourlyLimit, err = rtconfig.Int("NEXUS_SPAM_HOURLY_LIMIT", 6); err != nil {
		return nil, err
	}
	if s.SpamDailyLimit, err = rtconfig.Int("NEXUS_SPAM_DAILY_LIMIT", 30); err != nil {
		return nil, err
	}
	if s.ClusterExpireMinutes, err = rtconfig.Int("NEXUS_CLUSTER_EXPIRE_MINUTES", 90); err != nil {
		return nil, fmt.Errorf("NEXUS_CLUSTER_EXPIRE_MINUTES: %w", err)
	}
	return s, nil
}

func modelEnv(primary, legacy, fallback string) string {
	if value := strings.TrimSpace(rtconfig.String(primary, "")); value != "" {
		return value
	}
	return rtconfig.String(legacy, fallback)
}

func normalizeProvider(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "claude":
		return "anthropic"
	case "gpt":
		return "openai"
	default:
		return strings.ToLower(strings.TrimSpace(value))
	}
}

func providerOrder(raw, defaultProvider string) []string {
	seen := map[string]bool{}
	order := make([]string, 0, 3)
	add := func(value string) {
		provider := normalizeProvider(value)
		if provider == "" || seen[provider] {
			return
		}
		switch provider {
		case "anthropic", "openai", "gemini":
			seen[provider] = true
			order = append(order, provider)
		}
	}
	add(defaultProvider)
	for _, value := range strings.Split(raw, ",") {
		add(value)
	}
	return order
}
