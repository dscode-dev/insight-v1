// insight-gateway main.
//
// Boot order:
//  1. Load + validate config (fail fast on missing required env).
//  2. Init logger + tracer.
//  3. Connect Postgres + Redis (Ping at boot — fail fast if down).
//  4. Build auth dependencies (JWT codec, OTP codec, phone normalizer,
//     SMS provider, Social user-creation client, cooldown store).
//  5. Compose the application Service.
//  6. Build the router (standalone by default; legacy Strangler proxy
//     only when LEGACY_UPSTREAM_BASE_URL is set) + register handlers.
//  7. Mount middleware chain + start HTTP server.
//  8. Block on SIGINT/SIGTERM, then graceful shutdown.
package main

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"

	appauth "github.com/konoha-labs/insight-gateway/internal/application/auth"
	appmod "github.com/konoha-labs/insight-gateway/internal/application/moderation"
	authproviders "github.com/konoha-labs/insight-gateway/internal/auth/providers"
	"github.com/konoha-labs/insight-gateway/internal/config"
	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/authmetrics"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/jwt"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/modmetrics"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/otp"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/phone"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/postgres"
	redisstore "github.com/konoha-labs/insight-gateway/internal/infrastructure/redis"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/sms"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"

	"github.com/konoha-labs/insight-gateway/internal/infrastructure/avatarstore"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/socialclient"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/anvilproxy"
	httpauth "github.com/konoha-labs/insight-gateway/internal/interfaces/http/auth"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/communitybff"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/competitions"
	httpconsole "github.com/konoha-labs/insight-gateway/internal/interfaces/http/console"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/consolemw"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/edgelimit"
	httpevents "github.com/konoha-labs/insight-gateway/internal/interfaces/http/events"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/interactions"
	httpmoderation "github.com/konoha-labs/insight-gateway/internal/interfaces/http/moderation"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/notificationbff"
	httpoperator "github.com/konoha-labs/insight-gateway/internal/interfaces/http/operator"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/opsadmin"
	httprealtime "github.com/konoha-labs/insight-gateway/internal/interfaces/http/realtime"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/searchbff"
	httpsocial "github.com/konoha-labs/insight-gateway/internal/interfaces/http/social"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/proxy"
	"github.com/konoha-labs/insight-gateway/internal/realtime"

	"github.com/konoha-labs/insight-runtime-go/pkg/health"
	"github.com/konoha-labs/insight-runtime-go/pkg/logging"
	"github.com/konoha-labs/insight-runtime-go/pkg/metrics"
	"github.com/konoha-labs/insight-runtime-go/pkg/middleware"
	"github.com/konoha-labs/insight-runtime-go/pkg/tracing"
)

func main() {
	settings, err := config.Load()
	if err != nil {
		// Logger isn't up yet; use stderr.
		// nolint:forbidigo
		println("config load failed:", err.Error())
		os.Exit(1)
	}

	logger := logging.Init(logging.Config{
		Service: settings.Service,
		Version: settings.Version,
		Level:   settings.LogLevel,
		Pretty:  settings.LogPretty,
	})
	if err := settings.ValidateAuthProvider(); err != nil {
		logger.Fatal().
			Err(err).
			Str("auth_provider", settings.AuthProvider).
			Bool("supabase_url_set", settings.SupabaseURL != "").
			Bool("supabase_publishable_key_set", settings.SupabasePublishableKey != "").
			Msg("auth_provider_configuration_invalid")
	}
	logger.Info().
		Str("auth_provider", settings.AuthProvider).
		Bool("supabase_url_set", settings.SupabaseURL != "").
		Bool("supabase_publishable_key_set", settings.SupabasePublishableKey != "").
		Msg("auth_provider_configuration_loaded")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// ---- tracing ----
	shutdownTrace, err := tracing.Init(ctx, tracing.Config{
		Service:      settings.Service,
		Version:      settings.Version,
		OTLPEndpoint: settings.OTLPEndpoint,
		SampleRatio:  settings.OTLPSampleRatio,
	})
	if err != nil {
		logger.Fatal().Err(err).Msg("tracing_init_failed")
	}

	// ---- postgres ----
	pgPool, err := postgres.Connect(ctx, settings.DatabaseURL,
		settings.DatabasePoolSize, settings.DatabaseMaxOverflow)
	if err != nil {
		logger.Fatal().Err(err).Msg("postgres_connect_failed")
	}
	defer pgPool.Close()
	logger.Info().Msg("postgres_connected")

	// ---- redis ----
	redisOpts, err := redis.ParseURL(settings.RedisURL)
	if err != nil {
		logger.Fatal().Err(err).Msg("redis_url_invalid")
	}
	redisClient := redis.NewClient(redisOpts)
	defer func() { _ = redisClient.Close() }()
	if err := redisClient.Ping(ctx).Err(); err != nil {
		logger.Fatal().Err(err).Msg("redis_ping_failed")
	}
	logger.Info().Msg("redis_connected")

	// ---- social gRPC client (W2.2) ----
	// Dialed once at boot; injected into the BFF Handlers AND the auth
	// service (user creation goes through social.v1.UserService).
	// Lifetime bound to graceful shutdown via socialConn.Close().
	socialConn, err := socialclient.New(ctx, socialclient.Config{
		Target:      settings.SocialGrpcAddr,
		TLSCertPath: settings.SocialTLSCertPath,
		TLSKeyPath:  settings.SocialTLSKeyPath,
		TLSCAPath:   settings.SocialTLSCAPath,
		ServerName:  settings.SocialTLSServerName,
	})
	if err != nil {
		// Don't fatal — the gateway still serves OTP/refresh/realtime/
		// meta routes. Boot proceeds with a nil client: the social BFF
		// routes never get registered and registration returns a clear
		// error until social recovers.
		logger.Warn().Err(err).
			Str("target", settings.SocialGrpcAddr).
			Msg("social_dial_failed_bff_routes_skipped")
	} else {
		defer func() { _ = socialConn.Close() }()
		logger.Info().Str("target", settings.SocialGrpcAddr).Msg("social_connected")
	}

	var userCreator domauth.UserCreator = socialclient.UnavailableUserCreator{}
	if socialConn != nil {
		userCreator = socialclient.NewUserCreator(socialConn)
	}

	// ---- metrics registry ----
	// Created before the auth service so auth_* counters (Auth-A Part 10)
	// register on the same registry the broker + social BFF use.
	m := metrics.New()

	// ---- auth dependencies (built lazily — only used by native handlers) ----
	// authSvc handles the 4 OTP endpoints; tokenCodec also used by the
	// SSE handler to validate access_token in the query string.
	authSvc, tokenCodec := buildAuthService(settings, pgPool, redisClient, userCreator, m.Registry, logger)

	// ---- Store-A: moderation (UGC safety) ----
	// Gateway-owned: blocks, reports, admin actions, hidden content + bans.
	// The social BFF filters proxied responses through it; the auth layer
	// enforces bans; the Console drives the admin surface.
	moderationSvc := appmod.NewService(appmod.Deps{
		Repo:    postgres.NewModerationRepo(pgPool),
		Metrics: modmetrics.New(m.Registry),
	})

	// ---- realtime broker ----
	// Start one goroutine that tails every derived-stream partition
	// (insight:stream:derived:p0..pN-1) and fans events to subscribers.
	// Lifetime is bound to ctx — graceful shutdown cancels it.
	streamKeys := make([]string, settings.StreamPartitions)
	for i := 0; i < settings.StreamPartitions; i++ {
		streamKeys[i] = fmt.Sprintf("%s:p%d", settings.DerivedStreamBaseKey, i)
	}

	// ---- avatar storage (Sprint C) ----
	// Optional: when MINIO_ENDPOINT is empty, the avatar upload route
	// stays unregistered and the Flutter UI keeps rendering initials.
	var avatarStore *avatarstore.Store
	if settings.MinioEndpoint != "" {
		avatarStore, err = avatarstore.New(avatarstore.Config{
			Endpoint:        settings.MinioEndpoint,
			UseSSL:          settings.MinioUseSSL,
			AccessKeyID:     settings.MinioAccessKeyID,
			SecretAccessKey: settings.MinioSecretAccessKey,
			Bucket:          settings.MinioBucket,
			PublicBaseURL:   settings.MinioPublicBaseURL,
			MaxObjectBytes:  int64(settings.AvatarMaxBytes),
		})
		if err != nil {
			logger.Warn().Err(err).Msg("avatar_store_init_failed_route_skipped")
			avatarStore = nil
		} else {
			avatarCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
			err = avatarStore.EnsureBucket(avatarCtx)
			cancel()
			if err != nil {
				logger.Warn().Err(err).Msg("avatar_store_bucket_unavailable_route_skipped")
				avatarStore = nil
			}
		}
		if avatarStore != nil {
			logger.Info().
				Str("endpoint", settings.MinioEndpoint).
				Str("bucket", settings.MinioBucket).
				Msg("avatar_store_ready")
		}
	}

	// ---- router (standalone by default; legacy proxy in overlap) ----
	strangler, err := proxy.New(settings.LegacyUpstreamBaseURL)
	if err != nil {
		logger.Fatal().Err(err).Msg("router_init_failed")
	}
	if strangler.HasUpstream() {
		logger.Warn().Str("upstream", strangler.UpstreamURL()).
			Msg("legacy_upstream_proxy_enabled")
	} else {
		logger.Info().Msg("router_standalone_ready")
	}

	// ---- health + broker (metrics registry built above) ----
	broker := realtime.NewBroker(realtime.BrokerConfig{
		Redis:              redisClient,
		StreamKeys:         streamKeys,
		BlockMs:            settings.RealtimeBlockMs,
		SubscriberQueueMax: settings.RealtimeSubscriberQueueMax,
	}, m.Registry)
	go broker.Run(logger.WithContext(ctx))
	logger.Info().
		Strs("streams", streamKeys).
		Int("block_ms", settings.RealtimeBlockMs).
		Msg("realtime_broker_started")
	hc := health.New()
	hc.AddReadiness("postgres", func(ctx context.Context) error {
		return pgPool.Ping(ctx)
	})
	hc.AddReadiness("redis", func(ctx context.Context) error {
		return redisClient.Ping(ctx).Err()
	})
	if strangler.HasUpstream() {
		hc.AddReadiness("legacy_upstream", func(ctx context.Context) error {
			req, _ := http.NewRequestWithContext(ctx, http.MethodGet,
				settings.LegacyUpstreamBaseURL+"/ready", nil)
			client := &http.Client{Timeout: 2 * time.Second}
			resp, err := client.Do(req)
			if err != nil {
				return err
			}
			_ = resp.Body.Close()
			if resp.StatusCode >= 500 {
				return errors.New("upstream_unhealthy")
			}
			return nil
		})
	}

	// ---- native routes (always Go, no proxy fallback) ----
	strangler.Native(http.MethodGet, "/metrics", m.Handler)
	strangler.Native(http.MethodGet, "/healthz", hc.Liveness())
	strangler.Native(http.MethodGet, "/readyz", hc.Readiness())

	operatorHandlers := httpoperator.NewHandlers(pgPool)
	strangler.Native(http.MethodPost, "/v1/operator/auth/login",
		http.HandlerFunc(operatorHandlers.Login))
	strangler.Native(http.MethodGet, "/v1/operator/auth/me",
		http.HandlerFunc(operatorHandlers.Me))
	strangler.Native(http.MethodPost, "/v1/operator/auth/refresh",
		http.HandlerFunc(operatorHandlers.Refresh))
	strangler.Native(http.MethodPost, "/v1/operator/auth/logout",
		http.HandlerFunc(operatorHandlers.Logout))
	logger.Info().Msg("operator_auth_routes_registered")

	// ---- console operations surface (CONSOLE-OPS-A2): operator-authed reads ----
	consoleHandlers := httpconsole.NewHandlers(
		pgPool, redisClient, socialConn,
		settings.AnvilAPIBaseURL, settings.ClickHouseHealthURL, settings.SocialHTTPBaseURL, settings.Version,
	)
	strangler.Native(http.MethodGet, "/v1/console/platform/health",
		http.HandlerFunc(consoleHandlers.PlatformHealth))
	strangler.Native(http.MethodGet, "/v1/console/audit",
		http.HandlerFunc(consoleHandlers.Audit))
	strangler.Native(http.MethodGet, "/v1/console/admin/users",
		http.HandlerFunc(consoleHandlers.AdminUsers))
	strangler.Native(http.MethodGet, "/v1/console/admin/operators",
		http.HandlerFunc(consoleHandlers.AdminOperators))
	strangler.Native(http.MethodGet, "/v1/console/admin/sessions",
		http.HandlerFunc(consoleHandlers.AdminSessions))
	// ---- canonical administrative audit spine (CONSOLE-SECURITY-A1) ----
	// Ingest is gated by BOTH the Console service token (consolemw) AND a verified
	// operator session (inside the handler). Operator identity is gateway-derived.
	requireConsoleSvc := consolemw.Require(settings.ConsoleServiceToken)
	strangler.Native(http.MethodPost, "/v1/console/audit/events",
		requireConsoleSvc(http.HandlerFunc(consoleHandlers.AuditIngest)))
	strangler.Native(http.MethodGet, "/v1/console/audit/events",
		http.HandlerFunc(consoleHandlers.AuditEvents))
	// ---- CONSOLE-IDENTITY-A: Operational Identity + Delegation (Gateway authority) ----
	// Service-token gated (consolemw) + verified operator session inside the handler.
	// The browser never forges identity; it may only reference a grant by id.
	strangler.Native(http.MethodGet, "/v1/console/identity/resolve",
		requireConsoleSvc(http.HandlerFunc(consoleHandlers.IdentityResolve)))
	strangler.Native(http.MethodGet, "/v1/console/identity/delegations",
		requireConsoleSvc(http.HandlerFunc(consoleHandlers.DelegationList)))
	strangler.Native(http.MethodPost, "/v1/console/identity/delegations",
		requireConsoleSvc(http.HandlerFunc(consoleHandlers.DelegationGrant)))
	strangler.Native(http.MethodDelete, "/v1/console/identity/delegations/{id}",
		requireConsoleSvc(http.HandlerFunc(consoleHandlers.DelegationRevoke)))
	// ---- Social read plane: REMOVED ------------------------------------
	//
	// Fifteen GET routes here were a pure proxy: they authenticated an
	// operator and forwarded to Social's own /console/social/* surface. Per
	// insight-context.md v2.0 the Gateway is not responsible for
	// administration, operators or the console, and the Insight Control Plane
	// is the service that talks to the rest of the platform. The Gateway was
	// a third party in a two-party conversation, and holding SOCIAL_OPS_TOKEN
	// to play it.
	//
	// The Console now reaches those reads as
	//   Console -> Control Plane -> Social  (src/social/ in insight-console-api)
	// with Social requiring its ops token on every route, reads included —
	// they previously required nothing, because the cluster boundary was the
	// whole protection.
	//
	// The POST enforcement routes below did NOT move, and the difference is
	// ownership, not effort: they mutate moderation state this service owns
	// (migrations/00004_moderation.sql). Moving them is a data migration into
	// Social, which the same document says owns Moderação and Enforcement.
	// See docs/adr/0001-social-administration-path.md.
	// ---- Social Enforcement Plane (CONSOLE-SOCIAL-B): operator-driven mutations ----
	// Every command: service-token (consolemw) + verified operator session (handler)
	// + capability authorization + canonical audit intent→outcome. Operator identity
	// is gateway-derived; the request body can never assert an actor. Reuses the
	// existing Gateway-owned enforcement (moderation) + Social-owned agent state.
	consoleHandlers.WithEnforcement(
		moderationSvc,
		postgres.NewRefreshSessionRepo(pgPool),
		httpconsole.NewAgentStateSetter(settings.SocialHTTPBaseURL, settings.SocialOpsToken),
	)
	for _, ep := range []struct {
		path string
		h    http.HandlerFunc
	}{
		{"/v1/console/social/users/{id}/suspend", consoleHandlers.SocialSuspendUser},
		{"/v1/console/social/users/{id}/unsuspend", consoleHandlers.SocialUnsuspendUser},
		{"/v1/console/social/users/{id}/ban", consoleHandlers.SocialBanUser},
		{"/v1/console/social/users/{id}/unban", consoleHandlers.SocialUnbanUser},
		{"/v1/console/social/posts/{id}/hide", consoleHandlers.SocialHidePost},
		{"/v1/console/social/posts/{id}/restore", consoleHandlers.SocialRestorePost},
		{"/v1/console/social/comments/{id}/hide", consoleHandlers.SocialHideComment},
		{"/v1/console/social/comments/{id}/restore", consoleHandlers.SocialRestoreComment},
		{"/v1/console/social/agents/{id}/deactivate", consoleHandlers.SocialDeactivateAgent},
		{"/v1/console/social/agents/{id}/reactivate", consoleHandlers.SocialReactivateAgent},
		{"/v1/console/social/reports/{id}/review", consoleHandlers.SocialReviewReport},
		{"/v1/console/social/reports/{id}/resolve", consoleHandlers.SocialResolveReport},
		{"/v1/console/social/reports/{id}/dismiss", consoleHandlers.SocialDismissReport},
	} {
		strangler.Native(http.MethodPost, ep.path, requireConsoleSvc(http.HandlerFunc(ep.h)))
	}
	// Enforcement-state read model (operator-authed; current state + history).
	strangler.Native(http.MethodGet, "/v1/console/social/enforcement/{type}/{id}",
		http.HandlerFunc(consoleHandlers.SocialEnforcementState))
	logger.Info().Msg("console_operations_routes_registered")

	// Robozão-only administrative execution surface. Operator authorization is
	// performed by Robozão; Gateway independently authenticates the calling
	// service and owns the session/DLQ integration contracts.
	opsHandlers, err := opsadmin.New(
		settings.GatewayOpsToken,
		settings.SportHubHTTPBaseURL,
		settings.SportHubOpsToken,
		postgres.NewRefreshSessionRepo(pgPool),
	)
	if err != nil {
		logger.Fatal().Err(err).Msg("ops_admin_configuration_invalid")
	}
	opsHandlers.WithSocial(
		moderationSvc,
		httpconsole.NewAgentStateSetter(settings.SocialHTTPBaseURL, settings.SocialOpsToken),
	)
	strangler.Native(
		http.MethodPost,
		"/v1/internal/operations/users/{id}/sessions/revoke",
		opsHandlers.Require(opsHandlers.RevokeSessions),
	)
	strangler.Native(
		http.MethodPost,
		"/v1/internal/operations/dlq/{id}/replay",
		opsHandlers.Require(opsHandlers.ReplayDLQ),
	)
	strangler.Native(
		http.MethodGet,
		"/v1/console/dlq",
		requireConsoleSvc(http.HandlerFunc(opsHandlers.ListDLQ)),
	)
	strangler.Native(
		http.MethodPost,
		"/v1/internal/operations/social/agents/{id}/{action}",
		opsHandlers.Require(opsHandlers.AgentState),
	)
	strangler.Native(
		http.MethodPost,
		"/v1/internal/operations/social/content/{type}/{id}/{action}",
		opsHandlers.Require(opsHandlers.ContentState),
	)
	logger.Info().
		Bool("ops_admin_enabled", settings.GatewayOpsToken != "").
		Msg("ops_admin_routes_registered")

	// ---- Featured Competitions Rail (AZTECA-HOME-A): proxied from social ----
	competitionsHandler := competitions.New(settings.SocialHTTPBaseURL)
	strangler.Native(http.MethodGet, "/v1/competitions/highlights",
		http.HandlerFunc(competitionsHandler.Highlights))
	logger.Info().Msg("competitions_rail_route_registered")

	// ---- Saved Posts + Boosts (AZTECA-SOCIAL-A): proxied from social ----
	// Registered (authenticated) inside the social-foundation route block below.
	interactionsHandler := interactions.New(settings.SocialHTTPBaseURL).
		WithWriteGate(func(ctx context.Context, userID uuid.UUID) (string, error) {
			// CONSOLE-SOCIAL-B: reuse the authoritative moderation write-gate so
			// banned/suspended users cannot boost/save.
			err := moderationSvc.EnsureCanAct(ctx, userID)
			switch {
			case err == nil:
				return "", nil
			case errors.Is(err, dommod.ErrUserBanned):
				return "account_banned", nil
			case errors.Is(err, dommod.ErrUserSuspended):
				return "account_suspended", nil
			default:
				return "", err
			}
		})

	if settings.AtlasAnvilAPIKey != "" &&
		settings.AnvilAPIBaseURL != "" &&
		settings.AnvilAPIKey != "" {
		anvilHandler, err := anvilproxy.New(anvilproxy.Config{
			AtlasAPIKey: settings.AtlasAnvilAPIKey,
			AnvilURL:    settings.AnvilAPIBaseURL,
			AnvilAPIKey: settings.AnvilAPIKey,
			Timeout:     time.Duration(settings.RequestTimeout) * time.Second,
		})
		if err != nil {
			logger.Fatal().Err(err).Msg("anvil_proxy_configuration_invalid")
		}
		strangler.Native(
			http.MethodGet,
			"/v1/internal/anvil/features/matches/{match_id}",
			http.HandlerFunc(anvilHandler.MatchFeatures),
		)
		logger.Info().Msg("atlas_anvil_gateway_route_registered")
	} else {
		logger.Warn().
			Bool("atlas_api_key_set", settings.AtlasAnvilAPIKey != "").
			Bool("anvil_url_set", settings.AnvilAPIBaseURL != "").
			Bool("anvil_api_key_set", settings.AnvilAPIKey != "").
			Msg("atlas_anvil_gateway_route_disabled")
	}

	// ---- flagged routes (Strangler decides per request) ----
	if authSvc != nil {
		ah := httpauth.NewHandlers(authSvc, postgres.NewCredentialRepo(pgPool))
		strangler.NativeFlagged(http.MethodPost, "/v1/auth/otp/request",
			http.HandlerFunc(ah.RequestOtp),
			proxy.ParseFlag(settings.EnableGoAuthOtpRequest))
		strangler.NativeFlagged(http.MethodPost, "/v1/auth/otp/verify",
			http.HandlerFunc(ah.VerifyOtp),
			proxy.ParseFlag(settings.EnableGoAuthOtpVerify))
		// Auth-A.1 canonical phone endpoints. These are always Gateway-owned;
		// provider selection happens inside the auth service.
		strangler.Native(http.MethodPost, "/v1/auth/phone/request",
			http.HandlerFunc(ah.RequestOtp))
		strangler.Native(http.MethodPost, "/v1/auth/phone/verify",
			http.HandlerFunc(ah.VerifyOtp))
		strangler.NativeFlagged(http.MethodPost, "/v1/auth/register",
			http.HandlerFunc(ah.Register),
			proxy.ParseFlag(settings.EnableGoAuthRegister))
		strangler.NativeFlagged(http.MethodPost, "/v1/auth/refresh",
			http.HandlerFunc(ah.Refresh),
			proxy.ParseFlag(settings.EnableGoAuthRefresh))
		strangler.Native(http.MethodPost, "/v1/auth/logout",
			http.HandlerFunc(ah.Logout))
		logger.Info().
			Str("otp_request", settings.EnableGoAuthOtpRequest).
			Str("otp_verify", settings.EnableGoAuthOtpVerify).
			Str("register", settings.EnableGoAuthRegister).
			Str("refresh", settings.EnableGoAuthRefresh).
			Str("auth_provider", settings.AuthProvider).
			Msg("auth_routes_registered")

		// Shared bearer-auth gate for native authed routes.
		requireAuth := authmw.Require(tokenCodec)

		// ---- Store-A: moderation routes ----
		// User-facing (Bearer auth): block/unblock + report. Gateway-owned,
		// independent of Social availability.
		modHandlers := httpmoderation.NewHandlers(moderationSvc)
		strangler.Native(http.MethodPost, "/v1/users/{id}/block",
			requireAuth(http.HandlerFunc(modHandlers.Block)))
		strangler.Native(http.MethodDelete, "/v1/users/{id}/block",
			requireAuth(http.HandlerFunc(modHandlers.Unblock)))
		strangler.Native(http.MethodPost, "/v1/reports",
			requireAuth(http.HandlerFunc(modHandlers.CreateReport)))
		// Admin (Console only): X-Console-Service-Token guard, no user JWT.
		requireConsole := consolemw.Require(settings.ConsoleServiceToken)
		strangler.Native(http.MethodGet, "/v1/admin/users/{id}/legal",
			requireConsole(http.HandlerFunc(ah.UserLegalAudit)))
		strangler.Native(http.MethodGet, "/v1/admin/moderation/reports",
			requireConsole(http.HandlerFunc(modHandlers.ListReports)))
		strangler.Native(http.MethodGet, "/v1/admin/moderation/stats",
			requireConsole(http.HandlerFunc(modHandlers.Stats)))
		strangler.Native(http.MethodGet, "/v1/admin/moderation/actions",
			requireConsole(http.HandlerFunc(modHandlers.ListActions)))
		strangler.Native(http.MethodPost, "/v1/admin/moderation/actions",
			requireConsole(http.HandlerFunc(modHandlers.Act)))
		logger.Info().
			Bool("console_admin_enabled", settings.ConsoleServiceToken != "").
			Msg("moderation_routes_registered")

		// SSE reuses the same JWT codec for access_token validation.
		// We mount it under both common methods — EventSource only
		// sends GET, but tests + future WS upgrades may use other verbs.
		sseHandler := httprealtime.NewHandler(broker,
			tokenCodec,
			time.Duration(settings.SseKeepaliveSecs)*time.Second)
		strangler.NativeFlagged(http.MethodGet, "/v1/realtime/sse",
			http.HandlerFunc(sseHandler.Stream),
			proxy.ParseFlag(settings.EnableGoRealtimeSSE))

		// Sprint 2.5 Part 15 — SSE FOUNDATION: authenticated heartbeat
		// channel; business events (feed updates, notifications, live
		// signals) ride this later without endpoint redesign.
		eventsHandler := httpevents.NewHandler(tokenCodec, 15*time.Second)
		strangler.Native(http.MethodGet, "/v1/events/stream",
			http.HandlerFunc(eventsHandler.Stream))
		logger.Info().
			Str("realtime_sse", settings.EnableGoRealtimeSSE).
			Msg("realtime_routes_registered")

		// ---- W2.2 social BFF routes ----
		// Only registered when socialConn dialed successfully — see
		// the earlier Warn branch. Each route is wrapped by authmw
		// for Authorization: Bearer enforcement.
		if socialConn != nil {
			socialHandlers := httpsocial.NewHandlers(httpsocial.Deps{
				Client:          socialConn,
				UpstreamTimeout: time.Duration(settings.SocialUpstreamTimeout) * time.Second,
			})

			strangler.NativeFlagged(http.MethodGet, "/v1/feed",
				requireAuth(http.HandlerFunc(socialHandlers.GetFeed)),
				proxy.ParseFlag(settings.EnableGoSocialFeed))
			strangler.NativeFlagged(http.MethodGet, "/v1/hub/bundle",
				requireAuth(http.HandlerFunc(socialHandlers.GetHubBundle)),
				proxy.ParseFlag(settings.EnableGoSocialHubBundle))
			// Community Detail is now served by the Community Orchestrator
			// (communitybff) as an AGGREGATE — see registration below with the
			// members/discussions/join/leave routes.
			strangler.NativeFlagged(http.MethodGet, "/v1/profile/me/bundle",
				requireAuth(http.HandlerFunc(socialHandlers.GetProfileBundle)),
				proxy.ParseFlag(settings.EnableGoSocialProfileBundle))

			// Sprint A — Discussion thread BFF. NOT flagged: these
			// routes never had a legacy counterpart. Registered as
			// plain Native so requests are always handled in Go.
			strangler.Native(http.MethodGet, "/v1/discussions/{discussion_id}",
				requireAuth(http.HandlerFunc(socialHandlers.GetDiscussion)))
			strangler.Native(http.MethodGet, "/v1/discussions/{discussion_id}/messages",
				requireAuth(http.HandlerFunc(socialHandlers.GetDiscussionMessages)))
			strangler.Native(http.MethodPost, "/v1/discussions/{discussion_id}/messages",
				requireAuth(http.HandlerFunc(socialHandlers.PostDiscussionMessage)))

			// Sprint B — Reactions on Discussions. Same Native posture:
			// no legacy counterpart.
			strangler.Native(http.MethodPost, "/v1/reactions/discussion/{discussion_id}",
				requireAuth(http.HandlerFunc(socialHandlers.ReactToDiscussion)))
			strangler.Native(http.MethodDelete, "/v1/reactions/discussion/{discussion_id}",
				requireAuth(http.HandlerFunc(socialHandlers.UnreactToDiscussion)))

			// Sprint D — User preferences (settings page). Native: no
			// legacy counterpart.
			strangler.Native(http.MethodGet, "/v1/users/me/preferences",
				requireAuth(http.HandlerFunc(socialHandlers.GetPreferences)))
			strangler.Native(http.MethodPut, "/v1/users/me/preferences",
				requireAuth(http.HandlerFunc(socialHandlers.UpdatePreferences)))

			// Sprint C — Avatar upload. Only registered when MinIO/S3
			// was configured + reachable at boot. The adapter wraps
			// socialConn.User into the narrow interface AvatarHandlers
			// depends on, so the avatar BFF doesn't reach into the
			// full socialClient surface.
			// AZTECA-QUALITY-A: a CONFIGURED capability that is currently unavailable
			// must not masquerade as a missing route. Previously the route was only
			// registered when avatarStore != nil, so an unconfigured/unavailable object
			// store (no MINIO_ENDPOINT, init failure, or bucket down) silently produced
			// a 404 - indistinguishable to the client from "feature does not exist". The
			// route is now ALWAYS registered; when storage is unavailable the handler
			// returns a normalized 503 CAPABILITY_UNAVAILABLE so the app can surface an
			// honest "avatar upload temporarily unavailable" state. Read-only profile
			// flows are unaffected; no secret is leaked.
			if avatarStore != nil {
				avatarHandlers := httpsocial.NewAvatarHandlers(
					&socialUserAvatarAdapter{conn: socialConn},
					avatarStore,
					int64(settings.AvatarMaxBytes),
				)
				strangler.Native(http.MethodPost, "/v1/users/me/avatar",
					requireAuth(http.HandlerFunc(avatarHandlers.UploadAvatar)))
				logger.Info().Msg("avatar_upload_route_registered")
			} else {
				strangler.Native(http.MethodPost, "/v1/users/me/avatar",
					requireAuth(http.HandlerFunc(avatarStorageUnavailable)))
				logger.Warn().
					Msg("avatar_upload_route_registered_degraded_storage_unavailable")
			}

			// ---- Sprint 2.5 — Social Foundation BFF ----
			// The complete social surface Azteca consumes: feeds,
			// agents, posts, comments, likes, follow, mute and the
			// polling new-posts probe. All Native (no legacy
			// counterpart), all behind requireAuth, all instrumented.
			socialMetrics := httpsocial.NewMetrics(m.Registry)
			foundation := httpsocial.NewFoundationHandlers(httpsocial.FoundationDeps{
				Feed:          socialConn.Feed,
				Agents:        socialConn.Agent,
				Posts:         socialConn.Post,
				Users:         socialConn.User,
				Relationships: socialConn.Relationship,
				Moderation:    moderationSvc,
				Metrics:       socialMetrics,
				UpstreamTimeout: time.Duration(
					settings.SocialUpstreamTimeout) * time.Second,
			})
			route := func(method, pattern, label string, fn http.HandlerFunc) {
				strangler.Native(method, pattern,
					requireAuth(socialMetrics.Instrument(label, fn)))
			}
			route(http.MethodGet, "/v1/feed/global", "feed_global", foundation.GlobalFeed)
			route(http.MethodGet, "/v1/feed/following", "feed_following", foundation.FollowingFeed)
			route(http.MethodGet, "/v1/feed/updates", "feed_updates", foundation.FeedUpdates)
			route(http.MethodGet, "/v1/agents", "agents_list", foundation.ListAgents)
			route(http.MethodGet, "/v1/agents/{agentId}", "agents_get", foundation.GetAgent)
			route(http.MethodGet, "/v1/agents/{agentId}/posts", "agents_posts", foundation.AgentPosts)
			route(http.MethodGet, "/v1/users/{userId}", "users_get", foundation.GetUser)
			route(http.MethodGet, "/v1/users/{userId}/posts", "users_posts", foundation.UserPosts)
			route(http.MethodPost, "/v1/posts", "posts_create", foundation.CreatePost)
			route(http.MethodGet, "/v1/posts/{postId}", "posts_get", foundation.GetPost)
			route(http.MethodDelete, "/v1/posts/{postId}", "posts_delete", foundation.DeletePost)
			route(http.MethodPost, "/v1/posts/{postId}/comments", "comments_create", foundation.CreateComment)
			route(http.MethodGet, "/v1/posts/{postId}/comments", "comments_list", foundation.ListComments)
			route(http.MethodPost, "/v1/posts/{postId}/like", "like", foundation.LikePost)
			route(http.MethodDelete, "/v1/posts/{postId}/like", "unlike", foundation.UnlikePost)
			// AZTECA-SOCIAL-A — Saved Posts + Boosts (proxied to social).
			route(http.MethodPost, "/v1/posts/{postId}/save", "save", interactionsHandler.Save)
			route(http.MethodDelete, "/v1/posts/{postId}/save", "unsave", interactionsHandler.Unsave)
			route(http.MethodPost, "/v1/posts/{postId}/boost", "boost", interactionsHandler.Boost)
			route(http.MethodDelete, "/v1/posts/{postId}/boost", "unboost", interactionsHandler.Unboost)
			route(http.MethodGet, "/v1/posts/interaction-states", "interaction_states", interactionsHandler.InteractionStates)
			route(http.MethodGet, "/v1/me/saved-posts", "saved_posts", interactionsHandler.SavedPosts)
			// AZTECA-IDENTITY-B — enriched Sports Profile (identity + grouped stats).
			route(http.MethodGet, "/v1/users/{userId}/sports-profile", "sports_profile", interactionsHandler.SportsProfile)
			// AZTECA-PROFILE-B — authenticated profile write (display_name only).
			route(http.MethodPatch, "/v1/users/me", "profile_update", interactionsHandler.UpdateMyProfile)
			route(http.MethodPost, "/v1/follow/{targetId}", "follow", foundation.Follow)
			route(http.MethodDelete, "/v1/follow/{targetId}", "unfollow", foundation.Unfollow)
			route(http.MethodPost, "/v1/mute/{targetId}", "mute", foundation.Mute)
			route(http.MethodDelete, "/v1/mute/{targetId}", "unmute", foundation.Unmute)
			logger.Info().Msg("social_foundation_routes_registered")

			// ---- FEATURE-SEARCH-V1 (Stage 2): Search Orchestrator ----
			// The Gateway OWNS the public discovery contract: per-category
			// endpoints + the aggregated /all view (normalized_score merge,
			// partial semantics, per-category cursors), per-user cache, per-user
			// rate limit, one correlation id across the fan-out, and the SAME
			// moderation lens the feed uses (banned/suspended users and
			// admin-hidden posts never appear in search).
			searchMetrics := searchbff.NewMetrics(m.Registry)
			searchClient := searchbff.NewSocialClient(settings.SocialHTTPBaseURL)
			searchAgg := searchbff.NewAggregator(searchClient, 4*time.Second, 5, searchMetrics)
			searchCache := searchbff.NewCache(30*time.Second, 2000)
			searchHandlers := searchbff.NewHandlers(searchClient, searchAgg, searchCache,
				searchModerationLens{svc: moderationSvc}, searchMetrics)
			strangler.Native(http.MethodGet, "/v1/search/all",
				requireAuth(http.HandlerFunc(searchHandlers.All)))
			strangler.Native(http.MethodGet, "/v1/search/users",
				requireAuth(searchHandlers.Category("users", searchClient.Users)))
			strangler.Native(http.MethodGet, "/v1/search/agents",
				requireAuth(searchHandlers.Category("agents", searchClient.Agents)))
			strangler.Native(http.MethodGet, "/v1/search/communities",
				requireAuth(searchHandlers.Category("communities", searchClient.Communities)))
			strangler.Native(http.MethodGet, "/v1/search/competitions",
				requireAuth(searchHandlers.Category("competitions", searchClient.Competitions)))
			strangler.Native(http.MethodGet, "/v1/search/matches",
				requireAuth(searchHandlers.Category("matches", searchClient.Matches)))
			strangler.Native(http.MethodGet, "/v1/search/posts",
				requireAuth(searchHandlers.Category("posts", searchClient.Posts)))
			strangler.Native(http.MethodGet, "/v1/search/history",
				requireAuth(http.HandlerFunc(searchHandlers.History)))
			strangler.Native(http.MethodDelete, "/v1/search/history",
				requireAuth(http.HandlerFunc(searchHandlers.ClearHistory)))
			strangler.Native(http.MethodGet, "/v1/search/capabilities",
				requireAuth(http.HandlerFunc(searchHandlers.Capabilities)))
			logger.Info().Msg("search_routes_registered")

			// ---- FEATURE-COMMUNITIES-V1 Stage 2 — Community Orchestrator ----
			// Aggregate detail + paginated members + Discussions-only feed +
			// join/leave. Viewer identity is the verified session (never body).
			communityMetrics := communitybff.NewMetrics(m.Registry)
			communitySocial := communitybff.NewGRPCGateway(socialConn.Community, socialConn.Discussion)
			communityAgg := communitybff.NewAggregator(communitySocial, communityMetrics)
			communityCache := communitybff.NewStatsCache(30*time.Second, 2000)
			communityHandlers := communitybff.NewHandlers(communitySocial, communityAgg, communityCache, communityMetrics)
			strangler.Native(http.MethodGet, "/v1/hub/communities/{community_id}",
				requireAuth(http.HandlerFunc(communityHandlers.GetDetail)))
			strangler.Native(http.MethodGet, "/v1/hub/communities/{community_id}/members",
				requireAuth(http.HandlerFunc(communityHandlers.GetMembers)))
			strangler.Native(http.MethodGet, "/v1/hub/communities/{community_id}/discussions",
				requireAuth(http.HandlerFunc(communityHandlers.GetDiscussions)))
			strangler.Native(http.MethodPost, "/v1/hub/communities/{community_id}/join",
				requireAuth(http.HandlerFunc(communityHandlers.Join)))
			strangler.Native(http.MethodDelete, "/v1/hub/communities/{community_id}/membership",
				requireAuth(http.HandlerFunc(communityHandlers.Leave)))
			logger.Info().Msg("community_routes_registered")

			// ---- FEATURE-NOTIFICATIONS-V1 Stage 2 — Notification Orchestrator ----
			// List (cursor + has_more + unread_count) + unread-count (cached a few
			// seconds) + per-item read + read-all. Viewer = verified session.
			notificationMetrics := notificationbff.NewMetrics(m.Registry)
			notificationSocial := notificationbff.NewGRPCGateway(socialConn.Notification)
			notificationAgg := notificationbff.NewAggregator(notificationSocial, notificationMetrics)
			notificationCache := notificationbff.NewUnreadCache(5*time.Second, 5000)
			notificationHandlers := notificationbff.NewHandlers(notificationSocial, notificationAgg, notificationCache, notificationMetrics)
			strangler.Native(http.MethodGet, "/v1/notifications",
				requireAuth(http.HandlerFunc(notificationHandlers.List)))
			strangler.Native(http.MethodGet, "/v1/notifications/unread-count",
				requireAuth(http.HandlerFunc(notificationHandlers.UnreadCount)))
			strangler.Native(http.MethodPatch, "/v1/notifications/read-all",
				requireAuth(http.HandlerFunc(notificationHandlers.MarkAllRead)))
			strangler.Native(http.MethodPatch, "/v1/notifications/{id}/read",
				requireAuth(http.HandlerFunc(notificationHandlers.MarkRead)))
			logger.Info().Msg("notification_routes_registered")

			logger.Info().
				Str("feed", settings.EnableGoSocialFeed).
				Str("hub_bundle", settings.EnableGoSocialHubBundle).
				Str("community_detail", settings.EnableGoSocialCommunityDetail).
				Str("profile_bundle", settings.EnableGoSocialProfileBundle).
				Msg("social_bff_routes_registered")
			logger.Info().Msg("discussion_thread_routes_registered_native")
		}
	} else {
		logger.Warn().Msg("auth_service_unavailable_auth_routes_unregistered")
	}

	// Rate limiting is a declared Gateway responsibility (insight-context.md
	// v2.0) that had no implementation at the edge — the only throttling in
	// the service lived inside two BFF handlers, so the endpoints nobody had
	// thought about were the unprotected ones. Auth paths get a much tighter
	// bucket: each OTP request costs a real SMS, and the per-phone cooldown
	// does nothing against an attacker rotating numbers.
	limiter := edgelimit.New(edgelimit.DefaultLimits())
	handler := middleware.Recovery()(
		middleware.RequestID()(
			middleware.BodyLimit(settings.BodyMaxBytes)(
				middleware.SecurityHeaders(middleware.SecurityHeadersConfig{
					EnableHSTS: settings.EnableHSTS,
					CSP:        settings.CSP,
				})(limiter.Middleware(strangler)),
			),
		),
	)
	handler = withContextLogger(handler, logger)

	server := &http.Server{
		Addr:              settings.HTTPAddr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		logger.Info().Str("addr", settings.HTTPAddr).Msg("http_listen")
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Fatal().Err(err).Msg("http_failed")
		}
	}()

	// ---- graceful shutdown ----
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	logger.Info().Msg("shutdown_start")

	shutdownCtx, scancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer scancel()

	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("http_shutdown_failed")
	}
	if err := shutdownTrace(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("trace_shutdown_failed")
	}
	logger.Info().Msg("shutdown_complete")
}

// buildAuthService wires the auth.Service AND exposes the TokenCodec
// it uses. The SSE handler reuses the same codec to validate
// access_token query params, so we expose it rather than rebuild it.
//
// Returns (nil, nil) and logs WARN when required secrets are absent
// — that's the supported state during W1.0/W1.1 when the gateway
// runs in pure-proxy mode. Callers must check for nil before wiring
// flagged routes.
func buildAuthService(
	settings *config.Settings,
	pgPool postgres.Pool,
	redisClient *redis.Client,
	users domauth.UserCreator,
	reg prometheus.Registerer,
	logger zerolog.Logger,
) (*appauth.Service, domauth.TokenCodec) {
	if settings.JWTSigningKey == "" || settings.OtpHMACSecret == "" {
		logger.Warn().
			Bool("jwt_signing_key_set", settings.JWTSigningKey != "").
			Bool("otp_hmac_secret_set", settings.OtpHMACSecret != "").
			Msg("auth_service_skip_missing_secrets")
		return nil, nil
	}

	credRepo := postgres.NewCredentialRepo(pgPool)
	chRepo := postgres.NewOtpChallengeRepo(pgPool)
	cooldown := redisstore.NewCooldownStore(redisClient, "")

	codes := otp.New(settings.OtpHMACSecret, settings.OtpCodeLength)
	normalizer := phone.New(settings.PhoneDefaultRegion)

	smsProvider := sms.NewFromConfig(sms.FactoryConfig{
		Provider:       settings.SMSProvider,
		ZenviaToken:    settings.ZenviaAPIToken,
		ZenviaSender:   settings.ZenviaSenderID,
		TwilioSID:      settings.TwilioAccountSID,
		TwilioToken:    settings.TwilioAuthToken,
		TwilioFrom:     settings.TwilioFromNumber,
		RequestTimeout: time.Duration(settings.RequestTimeout) * time.Second,
	})
	phoneProvider := authproviders.NewFromConfig(authproviders.FactoryConfig{
		Provider:       settings.AuthProvider,
		SupabaseURL:    settings.SupabaseURL,
		SupabaseKey:    settings.SupabasePublishableKey,
		RequestTimeout: time.Duration(settings.RequestTimeout) * time.Second,
	})
	if phoneProvider != nil {
		logger.Info().
			Str("auth_provider", phoneProvider.Name()).
			Msg("phone_auth_provider_enabled")
	} else {
		logger.Info().
			Str("auth_provider", settings.AuthProvider).
			Msg("local_gateway_otp_provider_enabled")
	}

	tokens := jwt.New(jwt.Config{
		SigningKey:      settings.JWTSigningKey,
		Issuer:          settings.JWTIssuer,
		Audience:        settings.JWTAudience,
		AccessTTL:       time.Duration(settings.JWTAccessTTLSecs) * time.Second,
		RefreshTTL:      time.Duration(settings.JWTRefreshTTLSecs) * time.Second,
		RegistrationTTL: time.Duration(settings.JWTRegistrationTTLSecs) * time.Second,
	})

	// Auth-A: server-side refresh sessions make refresh tokens revocable +
	// rotatable. Always wired (the table ships in migration 00003).
	sessions := postgres.NewRefreshSessionRepo(pgPool)

	// Auth-A Part 10: auth_* counters.
	authMetrics := authmetrics.New(reg)

	svc := appauth.NewService(
		appauth.Config{
			OtpCodeLength:      settings.OtpCodeLength,
			OtpTTL:             time.Duration(settings.OtpTTLSecs) * time.Second,
			OtpMaxAttempts:     settings.OtpMaxAttempts,
			OtpResendCooldown:  time.Duration(settings.OtpResendCooldownSecs) * time.Second,
			SmsMessageTemplate: settings.SMSMessageTemplate,
		},
		appauth.Deps{
			Credentials: credRepo,
			Challenges:  chRepo,
			Cooldown:    cooldown,
			Codes:       codes,
			CodeGen:     codes,
			Phone:       normalizer,
			PhoneAuth:   phoneProvider,
			SMS:         smsProvider,
			Tokens:      tokens,
			Users:       users,
			Sessions:    sessions,
			Metrics:     authMetrics,
		},
	)
	return svc, tokens
}

// socialUserAvatarAdapter narrows the full socialclient.Client down
// to the single method the avatar handler needs (UpdateUserAvatar).
// Keeps the avatar handler's dependency surface tight + lets it be
// unit-tested with a fake without dragging the full client in.
type socialUserAvatarAdapter struct {
	conn *socialclient.Client
}

func (a *socialUserAvatarAdapter) UpdateUserAvatar(ctx context.Context, req *socialv1.UpdateAvatarRequest) (*socialv1.User, error) {
	return a.conn.User.UpdateAvatar(ctx, req)
}

// searchModerationLens adapts the moderation service's ViewFor to the narrow
// interface the Search BFF filters through (same lens as the feed).
type searchModerationLens struct{ svc *appmod.Service }

func (l searchModerationLens) SearchView(ctx context.Context, viewerID string) (searchbff.ModerationView, error) {
	if l.svc == nil {
		return nil, nil
	}
	return l.svc.ViewFor(ctx, viewerID)
}

// avatarStorageUnavailable is served on POST /v1/users/me/avatar when avatar
// object storage is not configured/available (AZTECA-QUALITY-A). It returns a
// normalized 503 CAPABILITY_UNAVAILABLE so a client can distinguish "avatar
// upload is temporarily unavailable" from "this route/feature does not exist"
// (a 404). It leaks no infrastructure detail (no host, bucket, or credential).
func avatarStorageUnavailable(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusServiceUnavailable)
	_, _ = w.Write([]byte(
		`{"detail":"avatar_storage_unavailable","code":"CAPABILITY_UNAVAILABLE"}`))
}

// withContextLogger seeds every request's context with the global
// zerolog logger so downstream middleware sub-loggers (RequestID)
// derive from a known starting point.
func withContextLogger(next http.Handler, logger zerolog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestID := r.Header.Get("X-Request-Id")
		if requestID == "" {
			requestID = uuid.NewString()
		}
		ctxLogger := logger.With().
			Str("request_id", requestID).
			Logger()
		ctx := ctxLogger.WithContext(r.Context())
		w.Header().Set("X-Request-Id", requestID)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
