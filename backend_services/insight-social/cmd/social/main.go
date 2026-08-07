// insight-social main — W2.0 boot.
//
// Two listeners:
//   - gRPC (default :50051) — 7 social.v1 service stubs, all returning
//     codes.Unimplemented until W2.1 fills them in.
//   - HTTP (default :8080) — /healthz, /readyz, /metrics for kube
//     probes + Prometheus scrape. Separate listener because gRPC and
//     HTTP can't share a port without h2c gymnastics + we want
//     metrics scraping to behave like every other Insight service.
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/reflection"

	appagent "github.com/konoha-labs/insight-social/internal/application/agent"
	appcommunity "github.com/konoha-labs/insight-social/internal/application/community"
	appdiscussion "github.com/konoha-labs/insight-social/internal/application/discussion"
	appfeed "github.com/konoha-labs/insight-social/internal/application/feed"
	appnotification "github.com/konoha-labs/insight-social/internal/application/notification"
	apppost "github.com/konoha-labs/insight-social/internal/application/post"
	apppreferences "github.com/konoha-labs/insight-social/internal/application/preferences"
	appreaction "github.com/konoha-labs/insight-social/internal/application/reaction"
	apprelationship "github.com/konoha-labs/insight-social/internal/application/relationship"
	appreputation "github.com/konoha-labs/insight-social/internal/application/reputation"
	appsearch "github.com/konoha-labs/insight-social/internal/application/search"
	appsentiment "github.com/konoha-labs/insight-social/internal/application/sentiment"
	appsignal "github.com/konoha-labs/insight-social/internal/application/signal"
	appuser "github.com/konoha-labs/insight-social/internal/application/user"
	"github.com/konoha-labs/insight-social/internal/config"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/agentrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/communityrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/discussionrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/feedrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/notificationrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/postrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/preferencesrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/reactionrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/relationshiprepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/reputationrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/searchrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/sentimentrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/signalrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/userrepo"
	"github.com/konoha-labs/insight-social/internal/infrastructure/redis/humansignal"
	socialgrpc "github.com/konoha-labs/insight-social/internal/interfaces/grpc"
	"github.com/konoha-labs/insight-social/internal/interfaces/httpapi"

	"github.com/konoha-labs/insight-runtime-go/pkg/health"
	"github.com/konoha-labs/insight-runtime-go/pkg/logging"
	"github.com/konoha-labs/insight-runtime-go/pkg/metrics"
	"github.com/konoha-labs/insight-runtime-go/pkg/tracing"
)

func main() {
	settings, err := config.Load()
	if err != nil {
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

	// ---- aggregate composition ----
	// One slice per aggregate: repo → application service → handler.
	// All 7 social.v1 services now have real implementations (W2.1a
	// + W2.1b complete). No more Unimplemented stubs.
	// Sprint 3 (Social Foundation) — agents are first-class graph
	// citizens; every new user auto-follows the active set.
	agentRepo := agentrepo.New(pgPool)
	agentSvc := appagent.New(agentRepo)
	agentServer := socialgrpc.NewAgentServer(agentSvc)

	relationshipRepoEarly := relationshiprepo.New(pgPool)

	userRepo := userrepo.New(pgPool)
	userSvc := appuser.New(userRepo).
		WithAgentAutoFollow(agentSvc, relationshipRepoEarly)
	userServer := socialgrpc.NewUserServer(userSvc)

	// Sprint D — preferences (attached to UserServer post-construction).
	prefsRepo := preferencesrepo.New(pgPool)
	prefsSvc := apppreferences.New(prefsRepo)
	socialgrpc.NewPrefsAttacher(prefsSvc).AttachTo(userServer)

	communityRepo := communityrepo.New(pgPool)
	communitySvc := appcommunity.New(communityRepo)
	communityServer := socialgrpc.NewCommunityServer(communitySvc)

	discussionRepo := discussionrepo.New(pgPool)
	discussionSvc := appdiscussion.New(discussionRepo)
	discussionServer := socialgrpc.NewDiscussionServer(discussionSvc)

	// FEATURE-NOTIFICATIONS-V1 — read/mark surface for the Gateway. Creation
	// flows through the domain Publisher seam (notification.NewDirectPublisher),
	// instantiated by event producers — not wired here (no producers in Stage 1).
	notificationRepo := notificationrepo.New(pgPool)
	notificationSvc := appnotification.New(notificationRepo)
	notificationServer := socialgrpc.NewNotificationServer(notificationSvc)

	// Signal needs both a repo AND a Redis publisher — the only
	// aggregate with fan-out. Stream partitioning here MUST match
	// what the gateway broker subscribes to.
	signalPublisher, err := humansignal.New(humansignal.Config{
		Client:     redisClient,
		KeyPrefix:  settings.HumanSignalStreamPrefix,
		Partitions: settings.StreamPartitions,
	})
	if err != nil {
		logger.Fatal().Err(err).Msg("humansignal_publisher_build_failed")
	}
	signalRepo := signalrepo.New(pgPool)
	signalSvc := appsignal.New(signalRepo, signalPublisher)
	signalServer := socialgrpc.NewSignalServer(signalSvc)

	sentimentRepo := sentimentrepo.New(pgPool)
	sentimentSvc := appsentiment.New(sentimentRepo)
	sentimentServer := socialgrpc.NewSentimentServer(sentimentSvc)

	relationshipRepo := relationshipRepoEarly
	relationshipSvc := apprelationship.New(relationshipRepo)
	relationshipServer := socialgrpc.NewRelationshipServer(relationshipSvc)

	reputationRepo := reputationrepo.New(pgPool)
	reputationSvc := appreputation.New(reputationRepo)
	reputationServer := socialgrpc.NewReputationServer(reputationSvc)

	// Sprint B — Reactions (8th service).
	reactionRepo := reactionrepo.New(pgPool)
	reactionSvc := appreaction.New(reactionRepo)
	reactionServer := socialgrpc.NewReactionServer(reactionSvc)

	// Sprint 3 (Social Foundation) — posts/comments/likes + feeds.
	postRepo := postrepo.New(pgPool)
	// CONSOLE-SOCIAL-B: enforce agent operational state at the publication choke
	// point — a deactivated agent may not publish through ANY path (Nexus/workers).
	postSvc := apppost.New(postRepo).WithAgentGuard(agentRepo)
	postServer := socialgrpc.NewPostServer(postSvc)

	feedRepo := feedrepo.New(pgPool)
	feedSvc := appfeed.New(feedRepo, relationshipRepo, agentSvc)
	feedServer := socialgrpc.NewFeedServer(feedSvc)

	// ---- gRPC server ----
	grpcServer, err := buildGrpcServer(settings, logger)
	if err != nil {
		logger.Fatal().Err(err).Msg("grpc_server_build_failed")
	}
	registerServices(grpcServer,
		userServer, communityServer, discussionServer,
		signalServer, sentimentServer, relationshipServer, reputationServer,
		reactionServer, agentServer, postServer, feedServer, notificationServer,
	)
	// Reflection makes `grpcurl list` work in lab — invaluable when
	// debugging dialing problems from insight-gateway. Disabled in
	// prod overlay via env (future) when we don't want service
	// surface introspection from outside the cluster.
	reflection.Register(grpcServer)

	grpcLis, err := net.Listen("tcp", settings.GrpcAddr)
	if err != nil {
		logger.Fatal().Err(err).Str("addr", settings.GrpcAddr).Msg("grpc_listen_failed")
	}
	go func() {
		logger.Info().Str("addr", settings.GrpcAddr).Msg("grpc_serve")
		if err := grpcServer.Serve(grpcLis); err != nil {
			logger.Fatal().Err(err).Msg("grpc_serve_failed")
		}
	}()

	// ---- HTTP listener (probes + metrics) ----
	m := metrics.New()
	hc := health.New()
	hc.AddReadiness("postgres", func(ctx context.Context) error {
		return pgPool.Ping(ctx)
	})
	hc.AddReadiness("redis", func(ctx context.Context) error {
		return redisClient.Ping(ctx).Err()
	})

	httpMux := http.NewServeMux()
	httpMux.Handle("/metrics", m.Handler)
	httpMux.Handle("/healthz", hc.Liveness())
	httpMux.Handle("/readyz", hc.Readiness())
	// AZTECA-HOME-A: Featured Competitions Rail source of truth (read-only).
	httpMux.HandleFunc("/competitions/highlights", httpapi.CompetitionHighlights(pgPool))
	// AZTECA-SOCIAL-A: Saved Posts + Boosts source of truth. The Gateway proxies
	// these and forwards the authenticated user as X-User-Id (internal port).
	httpMux.HandleFunc("POST /posts/{postId}/save", httpapi.SavePost(pgPool))
	httpMux.HandleFunc("DELETE /posts/{postId}/save", httpapi.SavePost(pgPool))
	httpMux.HandleFunc("POST /posts/{postId}/boost", httpapi.BoostPost(pgPool))
	httpMux.HandleFunc("DELETE /posts/{postId}/boost", httpapi.BoostPost(pgPool))
	httpMux.HandleFunc("GET /posts/interaction-states", httpapi.InteractionStates(pgPool))
	httpMux.HandleFunc("GET /me/saved-posts", httpapi.SavedPosts(pgPool))
	// AZTECA-IDENTITY-B: enriched Sports Profile (identity + grouped stats +
	// versioned avatar) — single payload, source of truth.
	httpMux.HandleFunc("GET /users/{id}/sports-profile", httpapi.SportsProfile(pgPool))
	// AZTECA-PROFILE-B: authenticated profile write (display_name only). Gateway
	// forwards the verified user via X-User-Id.
	httpMux.HandleFunc("PATCH /users/me/profile", httpapi.UpdateMyProfile(pgPool))

	// FEATURE-SEARCH-V1 (Stage 1): unified discovery — one typed route per
	// category (own ranking + own cursor), private history, capabilities
	// contract. Gateway-only internal port; "All" aggregation is the Gateway's
	// job (Stage 2). Teams/Players: BLOCKED_BY_DOMAIN (no route exists).
	searchSvc := appsearch.New(searchrepo.New(pgPool))
	httpMux.HandleFunc("GET /search/users", httpapi.SearchUsers(searchSvc))
	httpMux.HandleFunc("GET /search/agents", httpapi.SearchAgents(searchSvc))
	httpMux.HandleFunc("GET /search/communities", httpapi.SearchCommunities(searchSvc))
	httpMux.HandleFunc("GET /search/competitions", httpapi.SearchCompetitions(searchSvc))
	httpMux.HandleFunc("GET /search/matches", httpapi.SearchMatches(searchSvc))
	httpMux.HandleFunc("GET /search/posts", httpapi.SearchPosts(searchSvc))
	httpMux.HandleFunc("GET /search/history", httpapi.SearchHistory(searchSvc))
	httpMux.HandleFunc("DELETE /search/history", httpapi.ClearSearchHistory(searchSvc))
	httpMux.HandleFunc("GET /search/capabilities", httpapi.SearchCapabilities(searchSvc))

	// ---- administrative surface (insight-context.md v2.0) -----------------
	//
	// Social is administered from the Insight Console, through the Insight
	// Control Plane — the only service allowed to reach the Google Cloud
	// plane from the Robozão. These routes are that surface.
	//
	// EVERY route requires SOCIAL_OPS_TOKEN, reads included. The fifteen
	// reads used to require nothing: they sat behind the Gateway inside the
	// cluster, and the network was the whole protection. Exposing Social to
	// the Control Plane removes that boundary, and fifteen unauthenticated
	// reads on a public ingress would hand over every user, post, comment and
	// community to whoever found the hostname.
	//
	// Mutations additionally require X-Operator-Id: a write with no named
	// actor produces an audit row that cannot answer "who".
	consoleRead := func(h http.HandlerFunc) http.HandlerFunc {
		return httpapi.RequireConsoleToken(settings.OpsToken, false, h)
	}
	consoleWrite := func(h http.HandlerFunc) http.HandlerFunc {
		return httpapi.RequireConsoleToken(settings.OpsToken, true, h)
	}

	// Read plane — projections over the Social source of truth.
	httpMux.HandleFunc("GET /console/social/overview", consoleRead(httpapi.ConsoleSocialOverview(pgPool)))
	httpMux.HandleFunc("GET /console/social/activity", consoleRead(httpapi.ConsoleSocialActivity(pgPool)))
	httpMux.HandleFunc("GET /console/social/users", consoleRead(httpapi.ConsoleSocialUsers(pgPool)))
	httpMux.HandleFunc("GET /console/social/users/{id}", consoleRead(httpapi.ConsoleSocialUser(pgPool)))
	httpMux.HandleFunc("GET /console/social/agents", consoleRead(httpapi.ConsoleSocialAgents(pgPool)))
	httpMux.HandleFunc("GET /console/social/agents/{id}", consoleRead(httpapi.ConsoleSocialAgent(pgPool)))
	httpMux.HandleFunc("GET /console/social/posts", consoleRead(httpapi.ConsoleSocialPosts(pgPool)))
	httpMux.HandleFunc("GET /console/social/posts/{id}", consoleRead(httpapi.ConsoleSocialPost(pgPool)))
	// Investigation plane.
	httpMux.HandleFunc("GET /console/social/comments", consoleRead(httpapi.ConsoleSocialComments(pgPool)))
	httpMux.HandleFunc("GET /console/social/comments/{id}", consoleRead(httpapi.ConsoleSocialComment(pgPool)))
	httpMux.HandleFunc("GET /console/social/communities", consoleRead(httpapi.ConsoleSocialCommunities(pgPool)))
	httpMux.HandleFunc("GET /console/social/communities/{id}", consoleRead(httpapi.ConsoleSocialCommunity(pgPool)))
	httpMux.HandleFunc("GET /console/social/relationships", consoleRead(httpapi.ConsoleSocialRelationships(pgPool)))
	httpMux.HandleFunc("GET /console/social/boosts", consoleRead(httpapi.ConsoleSocialBoosts(pgPool)))
	httpMux.HandleFunc("GET /console/social/timeline", consoleRead(httpapi.ConsoleSocialTimeline(pgPool)))
	// Agent operational state.
	httpMux.HandleFunc("POST /console/social/agents/{id}/deactivate",
		consoleWrite(httpapi.ConsoleSocialAgentState(agentRepo, false, settings.OpsToken)))
	httpMux.HandleFunc("POST /console/social/agents/{id}/reactivate",
		consoleWrite(httpapi.ConsoleSocialAgentState(agentRepo, true, settings.OpsToken)))

	// Competition registry. Social is the source of truth for competitions
	// platform-wide: the app's rail, the feed's partition and — via the
	// Control Plane — what the Explorer is allowed to collect. Writes require
	// a named operator (consoleWrite) because a registry change alters what
	// every user sees, and `updated_by` has to be able to answer who.
	httpMux.HandleFunc("GET /console/social/competitions",
		consoleRead(httpapi.ConsoleCompetitionsList(pgPool)))
	httpMux.HandleFunc("POST /console/social/competitions",
		consoleWrite(httpapi.ConsoleCompetitionCreate(pgPool)))
	httpMux.HandleFunc("PATCH /console/social/competitions/{id}",
		consoleWrite(httpapi.ConsoleCompetitionUpdate(pgPool)))
	httpMux.HandleFunc("DELETE /console/social/competitions/{id}",
		consoleWrite(httpapi.ConsoleCompetitionDelete(pgPool)))

	httpServer := &http.Server{
		Addr:              settings.HTTPAddr,
		Handler:           withContextLogger(httpMux, logger),
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		logger.Info().Str("addr", settings.HTTPAddr).Msg("http_listen")
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
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

	// Stop accepting new connections, drain in-flight gracefully.
	grpcServer.GracefulStop()
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("http_shutdown_failed")
	}
	if err := shutdownTrace(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("trace_shutdown_failed")
	}
	logger.Info().Msg("shutdown_complete")
}

// buildGrpcServer wires the standard interceptor stack (tracing + log
// + recovery) plus optional mTLS. mTLS is enforced when all three TLS
// paths are set; otherwise the server runs plaintext (lab).
func buildGrpcServer(settings *config.Settings, logger zerolog.Logger) (*grpc.Server, error) {
	opts := []grpc.ServerOption{
		grpc.MaxRecvMsgSize(settings.MaxRecvMsgBytes),
	}

	if settings.TLSCertPath != "" && settings.TLSKeyPath != "" && settings.TLSCAPath != "" {
		creds, err := loadServerTLS(settings.TLSCertPath, settings.TLSKeyPath, settings.TLSCAPath)
		if err != nil {
			return nil, fmt.Errorf("load tls: %w", err)
		}
		opts = append(opts, grpc.Creds(creds))
		logger.Info().Msg("grpc_mtls_enabled")
	} else {
		opts = append(opts, grpc.Creds(insecure.NewCredentials()))
		logger.Warn().Msg("grpc_running_plaintext_lab_only")
	}

	return grpc.NewServer(opts...), nil
}

// registerServices attaches all 7 social.v1 service handlers.
// Real servers are passed in as arguments so main() owns lifecycle
// (DB pool, redis client, publisher). No more stubs as of W2.1b.
func registerServices(
	s *grpc.Server,
	userServer *socialgrpc.UserServer,
	communityServer *socialgrpc.CommunityServer,
	discussionServer *socialgrpc.DiscussionServer,
	signalServer *socialgrpc.SignalServer,
	sentimentServer *socialgrpc.SentimentServer,
	relationshipServer *socialgrpc.RelationshipServer,
	reputationServer *socialgrpc.ReputationServer,
	reactionServer *socialgrpc.ReactionServer,
	agentServer *socialgrpc.AgentServer,
	postServer *socialgrpc.PostServer,
	feedServer *socialgrpc.FeedServer,
	notificationServer *socialgrpc.NotificationServer,
) {
	socialv1.RegisterUserServiceServer(s, userServer)
	socialv1.RegisterCommunityServiceServer(s, communityServer)
	socialv1.RegisterDiscussionServiceServer(s, discussionServer)
	socialv1.RegisterSignalServiceServer(s, signalServer)
	socialv1.RegisterSentimentServiceServer(s, sentimentServer)
	socialv1.RegisterRelationshipServiceServer(s, relationshipServer)
	socialv1.RegisterReputationServiceServer(s, reputationServer)
	socialv1.RegisterReactionServiceServer(s, reactionServer)
	socialv1.RegisterAgentServiceServer(s, agentServer)
	socialv1.RegisterPostServiceServer(s, postServer)
	socialv1.RegisterFeedServiceServer(s, feedServer)
	socialv1.RegisterNotificationServiceServer(s, notificationServer)
}

// loadServerTLS builds a TLS config that requires + verifies client
// certs against the supplied CA bundle. This is the mTLS posture
// expected of every Insight Go service in prod.
func loadServerTLS(certPath, keyPath, caPath string) (credentials.TransportCredentials, error) {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("load keypair: %w", err)
	}
	caBytes, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("read ca: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caBytes) {
		return nil, errors.New("ca bundle empty or malformed")
	}
	return credentials.NewTLS(&tls.Config{
		Certificates: []tls.Certificate{cert},
		ClientCAs:    pool,
		ClientAuth:   tls.RequireAndVerifyClientCert,
		MinVersion:   tls.VersionTLS13,
	}), nil
}

// withContextLogger seeds every request's context with the global
// zerolog logger.
func withContextLogger(next http.Handler, logger zerolog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := logger.WithContext(r.Context())
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
