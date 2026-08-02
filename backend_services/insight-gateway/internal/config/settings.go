// Package config holds the typed Settings struct + parser.
//
// Convention: every value comes from env. Required values use
// `config.MustString` and fail fast at startup. Optional values fall
// back to safe defaults inline.
//
// W1.0 scope: only the proxy + observability + Postgres knobs are
// actually consumed. Auth/JWT/OTP/SMS/realtime config slots are
// declared up-front so handlers added in W1.2-W1.4 don't reshape the
// struct.
package config

import (
	"fmt"
	"net/url"
	"os"
	"strings"

	rtconfig "github.com/konoha-labs/insight-runtime-go/pkg/config"
)

type Settings struct {
	// --- Service identity ---
	Service string // INSIGHT_SERVICE
	Version string // INSIGHT_VERSION (build SHA, set at image build time)

	// --- HTTP edge ---
	HTTPAddr       string // HTTP_ADDR (default :8080)
	RequestTimeout int    // REQUEST_TIMEOUT_SECONDS (default 10)
	BodyMaxBytes   int64  // DEFAULT_BODY_MAX_BYTES (default 1MiB)

	// --- Legacy proxy upstream (consolidation: default OFF) ---
	// Empty (the default) runs the Gateway STANDALONE: every route is
	// served natively and unmatched paths 404. Setting a URL re-enables
	// the legacy Strangler fallback — overlap deployments only.
	LegacyUpstreamBaseURL string // LEGACY_UPSTREAM_BASE_URL (optional)

	// --- Auth DB ---
	DatabaseURL         string // DATABASE_URL (postgresql://...)
	DatabasePoolSize    int    // DATABASE_POOL_SIZE (default 10)
	DatabaseMaxOverflow int    // DATABASE_MAX_OVERFLOW (default 20)
	AutoApplyMigrations bool   // AUTO_APPLY_MIGRATIONS (default false in prod)

	// --- Redis (rate limit + OTP cooldown + realtime broker tail) ---
	RedisURL string // REDIS_URL

	// --- Auth (JWT) ---
	JWTSigningKey          string // JWT_SIGNING_KEY (≥ 32 chars)
	JWTAlgorithm           string // JWT_ALGORITHM (default HS256)
	JWTIssuer              string // JWT_ISSUER
	JWTAudience            string // JWT_AUDIENCE
	JWTAccessTTLSecs       int    // JWT_ACCESS_TTL_SECONDS
	JWTRefreshTTLSecs      int    // JWT_REFRESH_TTL_SECONDS
	JWTRegistrationTTLSecs int    // JWT_REGISTRATION_TTL_SECONDS

	// --- Auth (OTP) ---
	OtpCodeLength         int    // OTP_CODE_LENGTH (default 6)
	OtpTTLSecs            int    // OTP_TTL_SECONDS (default 600)
	OtpMaxAttempts        int    // OTP_MAX_ATTEMPTS (default 5)
	OtpResendCooldownSecs int    // OTP_RESEND_COOLDOWN_SECONDS (default 60)
	OtpHMACSecret         string // OTP_HMAC_SECRET (≥ 32 chars; distinct from JWT key)
	PhoneDefaultRegion    string // PHONE_DEFAULT_REGION (default BR)

	// --- Auth provider (Auth-A.1) ---
	// Gateway owns phone verification provider selection. Supabase is an OTP
	// provider only; Insight identity/session ownership remains in Gateway.
	AuthProvider           string // AUTH_PROVIDER: local|supabase|firebase(standby)
	SupabaseURL            string // SUPABASE_URL
	SupabasePublishableKey string // SUPABASE_PUBLISHABLE_KEY (never service-role)

	// --- Moderation admin (Store-A) ---
	// Shared secret the Console sends as X-Console-Service-Token to reach the
	// /v1/admin/moderation/* surface. Empty disables the admin surface
	// (fail-closed). Must equal the Console's ADMIN_API_INTERNAL_TOKEN.
	ConsoleServiceToken string // CONSOLE_SERVICE_TOKEN
	GatewayOpsToken     string // GATEWAY_OPS_TOKEN; Robozão-only admin surface
	SportHubHTTPBaseURL string // SPORT_HUB_HTTP_BASE_URL
	SportHubOpsToken    string // SPORT_HUB_OPS_TOKEN

	// --- Atlas -> Gateway -> Anvil analytics bridge ---
	AtlasAnvilAPIKey string // ATLAS_ANVIL_API_KEY, authenticates Atlas at Gateway
	AnvilAPIBaseURL  string // ANVIL_API_BASE_URL, private Anvil HTTP endpoint
	AnvilAPIKey      string // ANVIL_API_KEY, authenticates Gateway at Anvil

	// --- Console platform health (CONSOLE-OPS-A2) ---
	// ClickHouse ping URL reachable from the gateway (e.g. http://clickhouse:8123/ping).
	// Empty => clickhouse health reports "not configured" (never fake-healthy).
	ClickHouseHealthURL string // CLICKHOUSE_HEALTH_URL

	// --- Social HTTP (AZTECA-HOME-A) ---
	// Base URL of insight-social's HTTP port, used to proxy read-only endpoints
	// the Gateway does not need a gRPC method for (e.g. competition highlights).
	SocialHTTPBaseURL string // SOCIAL_HTTP_BASE_URL (default http://insight-social:8080)
	SocialOpsToken    string // SOCIAL_OPS_TOKEN

	// --- SMS provider ---
	SMSProvider        string // SMS_PROVIDER: null|zenvia|twilio (default null)
	SMSMessageTemplate string // SMS_MESSAGE_TEMPLATE
	ZenviaAPIToken     string // ZENVIA_API_TOKEN
	ZenviaSenderID     string // ZENVIA_SENDER_ID (default "Insight")
	TwilioAccountSID   string // TWILIO_ACCOUNT_SID
	TwilioAuthToken    string // TWILIO_AUTH_TOKEN
	TwilioFromNumber   string // TWILIO_FROM_NUMBER

	// --- Social gRPC client (W2.2 cutover target) ---
	// Address of insight-social. Prefer `dns:///<headless-service>:50051`
	// so grpc-go's DNS resolver + round_robin LB spreads load across pods.
	SocialGrpcAddr        string // SOCIAL_GRPC_ADDR
	SocialTLSCertPath     string // SOCIAL_TLS_CERT_PATH (mTLS client cert)
	SocialTLSKeyPath      string // SOCIAL_TLS_KEY_PATH
	SocialTLSCAPath       string // SOCIAL_TLS_CA_PATH (CA bundle for verifying social's server cert)
	SocialTLSServerName   string // SOCIAL_TLS_SERVER_NAME (SNI override; empty = derive from addr)
	SocialUpstreamTimeout int    // SOCIAL_UPSTREAM_TIMEOUT_SECONDS (default 6)

	// --- Avatar storage (Sprint C — MinIO/S3) ---
	// Empty MinioEndpoint disables the avatar upload route; the
	// gateway boots fine without it (the Flutter UI just keeps
	// rendering initials).
	MinioEndpoint        string // MINIO_ENDPOINT (host:port, no scheme)
	MinioUseSSL          bool   // MINIO_USE_SSL
	MinioAccessKeyID     string // MINIO_ACCESS_KEY_ID
	MinioSecretAccessKey string // MINIO_SECRET_ACCESS_KEY
	MinioBucket          string // MINIO_BUCKET (default "avatars")
	MinioPublicBaseURL   string // MINIO_PUBLIC_BASE_URL (e.g. http://localhost:9000)
	AvatarMaxBytes       int    // AVATAR_MAX_BYTES (default 5 MiB)

	// --- Realtime (W1.3) ---
	// Stream key base + partition count must match Atlas's
	// DerivedPublisher exactly — broker tails `<base>:p0`..`<base>:pN-1`.
	DerivedStreamBaseKey       string // DERIVED_STREAM_BASE_KEY
	StreamPartitions           int    // STREAM_PARTITIONS
	RealtimeBlockMs            int    // REALTIME_BLOCK_MS
	RealtimeSubscriberQueueMax int    // REALTIME_SUBSCRIBER_QUEUE_MAX
	SseKeepaliveSecs           int    // SSE_KEEPALIVE_SECONDS

	// --- Strangler rollout flags (per-endpoint; legacy overlap only) ---
	// Meaningless in standalone mode (no upstream): native handlers
	// always serve. With a legacy upstream configured: empty / "off" /
	// "false" / "0" = proxy upstream, "shadow" = call Go in parallel,
	// "1".."100" = percent rollout. See internal/interfaces/proxy/flag.go.
	EnableGoAuthOtpRequest string // ENABLE_GO_AUTH_OTP_REQUEST
	EnableGoAuthOtpVerify  string // ENABLE_GO_AUTH_OTP_VERIFY
	EnableGoAuthRegister   string // ENABLE_GO_AUTH_REGISTER
	EnableGoAuthRefresh    string // ENABLE_GO_AUTH_REFRESH
	EnableGoRealtimeSSE    string // ENABLE_GO_REALTIME_SSE

	// W2.2 social BFF routes — same flag semantics as the auth routes
	// above.
	EnableGoSocialFeed            string // ENABLE_GO_SOCIAL_FEED
	EnableGoSocialHubBundle       string // ENABLE_GO_SOCIAL_HUB_BUNDLE
	EnableGoSocialCommunityDetail string // ENABLE_GO_SOCIAL_COMMUNITY_DETAIL
	EnableGoSocialProfileBundle   string // ENABLE_GO_SOCIAL_PROFILE_BUNDLE

	// --- Observability ---
	LogLevel        string  // LOG_LEVEL (debug|info|warn|error)
	LogPretty       bool    // LOG_PRETTY (default false; true only for local dev)
	OTLPEndpoint    string  // INSIGHT_OTLP_ENDPOINT (empty disables tracing)
	OTLPSampleRatio float64 // INSIGHT_OTLP_SAMPLE_RATIO (default 1.0; collector trims)

	// --- AppSec ---
	EnableHSTS bool   // ENABLE_HSTS (default false in lab)
	CSP        string // CSP_OVERRIDE (empty = use middleware default)
}

func Load() (*Settings, error) {
	s := &Settings{
		Service:               rtconfig.String("INSIGHT_SERVICE", "insight-gateway"),
		Version:               rtconfig.String("INSIGHT_VERSION", "dev"),
		HTTPAddr:              rtconfig.String("HTTP_ADDR", ":8080"),
		LegacyUpstreamBaseURL: rtconfig.String("LEGACY_UPSTREAM_BASE_URL", ""),
		DatabaseURL:           rtconfig.MustString("DATABASE_URL"),
		RedisURL:              rtconfig.MustString("REDIS_URL"),
		AutoApplyMigrations:   rtconfig.Bool("AUTO_APPLY_MIGRATIONS", false),

		// JWT — required when any flag flips above "off", but the gateway
		// boots fine in pure-proxy mode without it. Validation happens in
		// the auth Service constructor.
		JWTSigningKey: rtconfig.String("JWT_SIGNING_KEY", ""),
		JWTAlgorithm:  rtconfig.String("JWT_ALGORITHM", "HS256"),
		JWTIssuer:     rtconfig.String("JWT_ISSUER", "insight.gateway"),
		JWTAudience:   rtconfig.String("JWT_AUDIENCE", "insight.client"),

		// OTP — same conditional-required story as JWT.
		OtpHMACSecret:      rtconfig.String("OTP_HMAC_SECRET", ""),
		PhoneDefaultRegion: rtconfig.String("PHONE_DEFAULT_REGION", "BR"),

		// Gateway-owned phone auth provider (Auth-A.1).
		AuthProvider:           rtconfig.String("AUTH_PROVIDER", "local"),
		SupabaseURL:            rtconfig.String("SUPABASE_URL", ""),
		SupabasePublishableKey: firstEnv("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"),

		// Moderation admin surface (Store-A). Empty = admin surface disabled.
		ConsoleServiceToken: rtconfig.String("CONSOLE_SERVICE_TOKEN", ""),
		GatewayOpsToken:     rtconfig.String("GATEWAY_OPS_TOKEN", ""),
		SportHubHTTPBaseURL: rtconfig.String("SPORT_HUB_HTTP_BASE_URL", "http://sport-hub:8080"),
		SportHubOpsToken:    rtconfig.String("SPORT_HUB_OPS_TOKEN", ""),
		AtlasAnvilAPIKey:    rtconfig.String("ATLAS_ANVIL_API_KEY", ""),
		AnvilAPIBaseURL:     rtconfig.String("ANVIL_API_BASE_URL", ""),
		AnvilAPIKey:         rtconfig.String("ANVIL_API_KEY", ""),
		ClickHouseHealthURL: rtconfig.String("CLICKHOUSE_HEALTH_URL", ""),
		SocialHTTPBaseURL:   rtconfig.String("SOCIAL_HTTP_BASE_URL", "http://insight-social:8080"),
		SocialOpsToken:      rtconfig.String("SOCIAL_OPS_TOKEN", ""),

		// SMS
		SMSProvider: rtconfig.String("SMS_PROVIDER", "null"),
		SMSMessageTemplate: rtconfig.String("SMS_MESSAGE_TEMPLATE",
			"Seu código Insight é {code}. Não compartilhe com ninguém."),
		ZenviaAPIToken:   rtconfig.String("ZENVIA_API_TOKEN", ""),
		ZenviaSenderID:   rtconfig.String("ZENVIA_SENDER_ID", "Insight"),
		TwilioAccountSID: rtconfig.String("TWILIO_ACCOUNT_SID", ""),
		TwilioAuthToken:  rtconfig.String("TWILIO_AUTH_TOKEN", ""),
		TwilioFromNumber: rtconfig.String("TWILIO_FROM_NUMBER", ""),

		// Social gRPC client (W2.2). Default points at the in-cluster
		// headless Service the social repo declares; lab can override
		// to localhost:50051 via .env.
		SocialGrpcAddr:      rtconfig.String("SOCIAL_GRPC_ADDR", "dns:///insight-social-headless.insight.svc.cluster.local:50051"),
		SocialTLSCertPath:   rtconfig.String("SOCIAL_TLS_CERT_PATH", ""),
		SocialTLSKeyPath:    rtconfig.String("SOCIAL_TLS_KEY_PATH", ""),
		SocialTLSCAPath:     rtconfig.String("SOCIAL_TLS_CA_PATH", ""),
		SocialTLSServerName: rtconfig.String("SOCIAL_TLS_SERVER_NAME", ""),

		// Sprint C — MinIO / S3-compatible avatar storage.
		MinioEndpoint:        rtconfig.String("MINIO_ENDPOINT", ""),
		MinioUseSSL:          rtconfig.Bool("MINIO_USE_SSL", false),
		MinioAccessKeyID:     rtconfig.String("MINIO_ACCESS_KEY_ID", ""),
		MinioSecretAccessKey: rtconfig.String("MINIO_SECRET_ACCESS_KEY", ""),
		MinioBucket:          rtconfig.String("MINIO_BUCKET", "avatars"),
		MinioPublicBaseURL:   rtconfig.String("MINIO_PUBLIC_BASE_URL", ""),

		// Realtime broker / SSE tuning.
		DerivedStreamBaseKey: rtconfig.String("DERIVED_STREAM_BASE_KEY", "insight:stream:derived"),

		// Per-endpoint rollout flags. Defaults to "off" via empty string.
		EnableGoAuthOtpRequest: rtconfig.String("ENABLE_GO_AUTH_OTP_REQUEST", ""),
		EnableGoAuthOtpVerify:  rtconfig.String("ENABLE_GO_AUTH_OTP_VERIFY", ""),
		EnableGoAuthRegister:   rtconfig.String("ENABLE_GO_AUTH_REGISTER", ""),
		EnableGoAuthRefresh:    rtconfig.String("ENABLE_GO_AUTH_REFRESH", ""),
		EnableGoRealtimeSSE:    rtconfig.String("ENABLE_GO_REALTIME_SSE", ""),

		// W2.2 social BFF flags — default "" (= off) so no flip happens
		// until an operator sets the env explicitly.
		EnableGoSocialFeed:            rtconfig.String("ENABLE_GO_SOCIAL_FEED", ""),
		EnableGoSocialHubBundle:       rtconfig.String("ENABLE_GO_SOCIAL_HUB_BUNDLE", ""),
		EnableGoSocialCommunityDetail: rtconfig.String("ENABLE_GO_SOCIAL_COMMUNITY_DETAIL", ""),
		EnableGoSocialProfileBundle:   rtconfig.String("ENABLE_GO_SOCIAL_PROFILE_BUNDLE", ""),

		LogLevel:     rtconfig.String("LOG_LEVEL", "info"),
		LogPretty:    rtconfig.Bool("LOG_PRETTY", false),
		OTLPEndpoint: rtconfig.String("INSIGHT_OTLP_ENDPOINT", ""),
		EnableHSTS:   rtconfig.Bool("ENABLE_HSTS", false),
		CSP:          rtconfig.String("CSP_OVERRIDE", ""),
	}

	var err error
	if s.RequestTimeout, err = rtconfig.Int("REQUEST_TIMEOUT_SECONDS", 10); err != nil {
		return nil, fmt.Errorf("REQUEST_TIMEOUT_SECONDS: %w", err)
	}
	bodyMax, err := rtconfig.Int("DEFAULT_BODY_MAX_BYTES", 1<<20)
	if err != nil {
		return nil, fmt.Errorf("DEFAULT_BODY_MAX_BYTES: %w", err)
	}
	s.BodyMaxBytes = int64(bodyMax)
	if s.DatabasePoolSize, err = rtconfig.Int("DATABASE_POOL_SIZE", 10); err != nil {
		return nil, fmt.Errorf("DATABASE_POOL_SIZE: %w", err)
	}
	if s.DatabaseMaxOverflow, err = rtconfig.Int("DATABASE_MAX_OVERFLOW", 20); err != nil {
		return nil, fmt.Errorf("DATABASE_MAX_OVERFLOW: %w", err)
	}
	if s.JWTAccessTTLSecs, err = rtconfig.Int("JWT_ACCESS_TTL_SECONDS", 900); err != nil {
		return nil, fmt.Errorf("JWT_ACCESS_TTL_SECONDS: %w", err)
	}
	if s.JWTRefreshTTLSecs, err = rtconfig.Int("JWT_REFRESH_TTL_SECONDS", 2_592_000); err != nil {
		return nil, fmt.Errorf("JWT_REFRESH_TTL_SECONDS: %w", err)
	}
	if s.JWTRegistrationTTLSecs, err = rtconfig.Int("JWT_REGISTRATION_TTL_SECONDS", 600); err != nil {
		return nil, fmt.Errorf("JWT_REGISTRATION_TTL_SECONDS: %w", err)
	}
	if s.OtpCodeLength, err = rtconfig.Int("OTP_CODE_LENGTH", 6); err != nil {
		return nil, fmt.Errorf("OTP_CODE_LENGTH: %w", err)
	}
	if s.OtpTTLSecs, err = rtconfig.Int("OTP_TTL_SECONDS", 600); err != nil {
		return nil, fmt.Errorf("OTP_TTL_SECONDS: %w", err)
	}
	if s.OtpMaxAttempts, err = rtconfig.Int("OTP_MAX_ATTEMPTS", 5); err != nil {
		return nil, fmt.Errorf("OTP_MAX_ATTEMPTS: %w", err)
	}
	if s.OtpResendCooldownSecs, err = rtconfig.Int("OTP_RESEND_COOLDOWN_SECONDS", 60); err != nil {
		return nil, fmt.Errorf("OTP_RESEND_COOLDOWN_SECONDS: %w", err)
	}
	if s.StreamPartitions, err = rtconfig.Int("STREAM_PARTITIONS", 8); err != nil {
		return nil, fmt.Errorf("STREAM_PARTITIONS: %w", err)
	}
	if s.RealtimeBlockMs, err = rtconfig.Int("REALTIME_BLOCK_MS", 2000); err != nil {
		return nil, fmt.Errorf("REALTIME_BLOCK_MS: %w", err)
	}
	if s.RealtimeSubscriberQueueMax, err = rtconfig.Int("REALTIME_SUBSCRIBER_QUEUE_MAX", 1000); err != nil {
		return nil, fmt.Errorf("REALTIME_SUBSCRIBER_QUEUE_MAX: %w", err)
	}
	if s.SseKeepaliveSecs, err = rtconfig.Int("SSE_KEEPALIVE_SECONDS", 15); err != nil {
		return nil, fmt.Errorf("SSE_KEEPALIVE_SECONDS: %w", err)
	}
	if s.OTLPSampleRatio, err = rtconfig.Float("INSIGHT_OTLP_SAMPLE_RATIO", 1.0); err != nil {
		return nil, fmt.Errorf("INSIGHT_OTLP_SAMPLE_RATIO: %w", err)
	}
	if s.SocialUpstreamTimeout, err = rtconfig.Int("SOCIAL_UPSTREAM_TIMEOUT_SECONDS", 6); err != nil {
		return nil, fmt.Errorf("SOCIAL_UPSTREAM_TIMEOUT_SECONDS: %w", err)
	}
	if s.AvatarMaxBytes, err = rtconfig.Int("AVATAR_MAX_BYTES", 5<<20); err != nil {
		return nil, fmt.Errorf("AVATAR_MAX_BYTES: %w", err)
	}

	return s, nil
}

func (s *Settings) ValidateAuthProvider() error {
	switch strings.ToLower(strings.TrimSpace(s.AuthProvider)) {
	case "", "local":
		return nil
	case "firebase":
		return fmt.Errorf("AUTH_PROVIDER=firebase is standby only in Auth-A.2")
	case "supabase":
		if strings.TrimSpace(s.SupabaseURL) == "" {
			return fmt.Errorf("AUTH_PROVIDER=supabase requires SUPABASE_URL")
		}
		if strings.TrimSpace(s.SupabasePublishableKey) == "" {
			return fmt.Errorf("AUTH_PROVIDER=supabase requires SUPABASE_PUBLISHABLE_KEY")
		}
		u, err := url.Parse(strings.TrimSpace(s.SupabaseURL))
		if err != nil || u.Scheme == "" || u.Host == "" {
			return fmt.Errorf("SUPABASE_URL must be an absolute URL")
		}
		return nil
	default:
		return fmt.Errorf("unsupported AUTH_PROVIDER %q", s.AuthProvider)
	}
}

func firstEnv(keys ...string) string {
	for _, key := range keys {
		if v := strings.TrimSpace(os.Getenv(key)); v != "" {
			return v
		}
	}
	return ""
}
