// insight-nexus — composition root.
//
// Nexus converts intelligence into communication: it consumes Atlas's
// evaluated trends off insight:stream:trends (its ONLY input), routes them
// to persisted agents, builds memory-aware contexts, generates structured
// drafts, enqueues them onto per-agent publishing queues, and — in a
// SEPARATE worker — composes and publishes them to Social.
//
// What it still does NOT do: any intelligence of its own. It never computes
// similarity, never collects data, never serves a public API. Atlas decided;
// Nexus only chooses whether and how to say it.
//
// (The trailing "no LLMs, no social output" that used to close this comment
// described Sprint 3 and stopped being true in Sprint 4. It is called out
// because the sentence stayed there long enough to mislead.)
//
// Two long-running loops:
//
//	trend consumer  → pipeline  → per-agent publishing queue   (fast path)
//	publish worker  ← queue     → LLM → validate → Social      (slow path)
//
// They are separate because the slow path takes up to one LLM timeout per
// provider. Running it inside the consumer stalled every other agent and
// every later trend.
package main

import (
	"context"
	"errors"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/konoha-labs/insight-runtime-go/pkg/logging"

	"github.com/konoha-labs/insight-nexus/internal/adapters/httpapi"
	"github.com/konoha-labs/insight-nexus/internal/adapters/llm"
	"github.com/konoha-labs/insight-nexus/internal/adapters/observability"
	"github.com/konoha-labs/insight-nexus/internal/adapters/postgres"
	"github.com/konoha-labs/insight-nexus/internal/adapters/redisstream"
	socialadapter "github.com/konoha-labs/insight-nexus/internal/adapters/social"
	"github.com/konoha-labs/insight-nexus/internal/application/agentstate"
	"github.com/konoha-labs/insight-nexus/internal/application/antispam"
	"github.com/konoha-labs/insight-nexus/internal/application/clustering"
	"github.com/konoha-labs/insight-nexus/internal/application/clusterlifecycle"
	"github.com/konoha-labs/insight-nexus/internal/application/contextbuilder"
	"github.com/konoha-labs/insight-nexus/internal/application/draftgen"
	"github.com/konoha-labs/insight-nexus/internal/application/draftvalidator"
	"github.com/konoha-labs/insight-nexus/internal/application/evolution"
	"github.com/konoha-labs/insight-nexus/internal/application/llmrouter"
	"github.com/konoha-labs/insight-nexus/internal/application/matchsweep"
	"github.com/konoha-labs/insight-nexus/internal/application/narrativehealth"
	"github.com/konoha-labs/insight-nexus/internal/application/pipeline"
	"github.com/konoha-labs/insight-nexus/internal/application/publication"
	"github.com/konoha-labs/insight-nexus/internal/application/publisher"
	"github.com/konoha-labs/insight-nexus/internal/application/publishworker"
	"github.com/konoha-labs/insight-nexus/internal/application/router"
	"github.com/konoha-labs/insight-nexus/internal/config"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	ops "github.com/konoha-labs/insight-nexus/internal/operations"
	portllm "github.com/konoha-labs/insight-nexus/internal/ports/llm"
	operationsv1 "github.com/konoha-labs/insight-protos/gen/go/operations/v1"
	"google.golang.org/grpc"
)

func main() {
	settings, err := config.Load()
	if err != nil {
		println("config load failed:", err.Error())
		os.Exit(1)
	}

	logger := logging.Init(logging.Config{
		Service: settings.Service,
		Version: settings.Version,
		Level:   settings.LogLevel,
		Pretty:  settings.LogPretty,
	})

	if settings.ClaimerMinIdleDerived {
		logger.Info().
			Int("min_idle_sec", settings.ClaimerMinIdleSec).
			Int("llm_timeout_sec", settings.LLMTimeoutSec).
			Int("providers", len(settings.ProviderOrder)).
			Msg("claimer_min_idle_raised_to_handler_worst_case")
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// ---- postgres ----
	pool, err := postgres.Connect(ctx, settings.DatabaseURL)
	if err != nil {
		logger.Fatal().Err(err).Msg("postgres_connect_failed")
	}
	defer pool.Close()

	agentRepo := postgres.NewAgentRepo(pool)
	memoryRepo := postgres.NewMemoryRepo(pool)
	draftRepo := postgres.NewDraftRepo(pool)
	pubRepo := postgres.NewPublicationRepo(pool)
	clusterRepo := postgres.NewClusterRepo(pool)
	decisionRepo := postgres.NewDecisionRepo(pool)
	stateRepo := postgres.NewAgentStateRepo(pool)
	evolutionRepo := postgres.NewEvolutionRepo(pool)

	// ---- metrics ----
	metrics := observability.New()
	pubMetrics := observability.NewPublicationMetrics()

	// ---- redis (consumer + per-agent queues) ----
	consumer, err := redisstream.NewConsumer(ctx, redisstream.ConsumerConfig{
		Addr:     settings.RedisAddr,
		Password: settings.RedisPassword,
		DB:       settings.RedisDB,
		Stream:   settings.TrendStream,
		Group:    settings.ConsumerGroup,
		Consumer: settings.ConsumerName,
		Claimer: redisstream.ClaimerConfig{
			Enabled:       settings.ClaimerEnabled,
			MinIdle:       time.Duration(settings.ClaimerMinIdleSec) * time.Second,
			Interval:      time.Duration(settings.ClaimerIntervalSec) * time.Second,
			MaxDeliveries: int64(settings.ClaimerMaxDeliveries),
			DLQStream:     settings.DLQStream,
		},
	}, logger)
	if err != nil {
		logger.Fatal().Err(err).Msg("trend_consumer_init_failed")
	}
	defer func() { _ = consumer.Close() }()

	queue, err := redisstream.NewQueue(ctx, redisstream.QueueConfig{
		Addr:     settings.RedisAddr,
		Password: settings.RedisPassword,
		DB:       settings.RedisDB,
		MaxLen:   settings.QueueMaxLen,
		Group:    settings.PublishConsumerGroup,
		Consumer: settings.PublishConsumerName,
	}, logger)
	if err != nil {
		logger.Fatal().Err(err).Msg("draft_queue_init_failed")
	}
	defer func() { _ = queue.Close() }()

	// ---- Sprint 4 — publication engine ----
	// Private provider chain. Local models are never registered in Nexus.
	llmTimeout := time.Duration(settings.LLMTimeoutSec) * time.Second
	providerByName := map[string]portllm.Provider{}
	if settings.EnableAnthropic {
		providerByName["anthropic"] = llm.NewAnthropic(
			settings.AnthropicKey, "", settings.AnthropicModel, llmTimeout)
	}
	if settings.EnableOpenAI {
		providerByName["openai"] = llm.NewOpenAI(
			settings.OpenAIKey, "", settings.OpenAIModel, llmTimeout)
	}
	if settings.EnableGemini {
		providerByName["gemini"] = llm.NewGemini(
			settings.GeminiKey, "", settings.GeminiModel, llmTimeout)
	}
	providers := make([]portllm.Provider, 0, len(providerByName))
	for _, name := range settings.ProviderOrder {
		if provider := providerByName[name]; provider != nil {
			providers = append(providers, provider)
		}
	}
	healthMgr := llmrouter.NewHealthManager(providers,
		time.Duration(settings.LLMHealthIntervalSec)*time.Second,
		pubMetrics, logger)
	go healthMgr.Run(ctx)
	llmRouter := llmrouter.NewRouter(providers, healthMgr, pubMetrics, logger)

	personaRepo := postgres.NewPersonaRepo(pool)
	candidateRepo := postgres.NewCandidateRepo(pool)
	ticketRepo := postgres.NewTicketRepo(pool)
	spamEngine := antispam.New(antispam.Policy{
		AgentCooldown:   time.Duration(settings.SpamAgentCooldownMin) * time.Minute,
		ClusterCooldown: time.Duration(settings.SpamClusterCooldownMin) * time.Minute,
		TrendCooldown:   time.Duration(settings.SpamTrendCooldownMin) * time.Minute,
		MatchCooldown:   time.Duration(settings.SpamMatchCooldownMin) * time.Minute,
		HourlyLimit:     settings.SpamHourlyLimit,
		DailyLimit:      settings.SpamDailyLimit,
	}, postgres.NewSpamLog(pool), pubMetrics, nil)

	var pubEngine *publisher.Engine
	pubUnavailableReason := "publication disabled by configuration"
	if settings.PublisherEnabled {
		socialPub, serr := socialadapter.New(ctx, settings.SocialGrpcAddr)
		if serr != nil {
			// Social unreachable at boot is NOT fatal: the publisher
			// stays off and drafts keep queueing (no content is lost;
			// publication resumes on restart once Social is up).
			logger.Warn().Err(serr).Msg("social_dial_failed_publisher_disabled")
			pubUnavailableReason = "publication unavailable: Social connection failed"
		} else {
			defer func() { _ = socialPub.Close() }()
			pubEngine = publisher.New(
				personaRepo, llmRouter, draftvalidator.New(), spamEngine,
				candidateRepo, ticketRepo, socialPub, memoryRepo,
				pubMetrics, logger, nil,
			)
			logger.Info().Msg("publication_engine_enabled")
		}
	} else {
		logger.Info().Msg("publication_engine_disabled_by_config")
	}

	// ---- application ----
	expireAfter := time.Duration(settings.ClusterExpireMinutes) * time.Minute
	lifecycleEngine := clusterlifecycle.New(clusterRepo,
		clusterlifecycle.Config{ExpireAfter: expireAfter}, logger, nil)
	sweepEngine := matchsweep.New(stateRepo, lifecycleEngine,
		matchsweep.Config{}, logger, nil)
	healthEngine := narrativehealth.New(clusterRepo, evolutionRepo,
		narrativehealth.Weights{}, nil)
	pipe := pipeline.New(pipeline.Deps{
		Router:       router.New(agentRepo, logger),
		Clustering:   clustering.New(clusterRepo, nil, expireAfter),
		Lifecycle:    lifecycleEngine,
		Sweep:        sweepEngine,
		Decisions:    publication.New(publication.Config{}),
		States:       agentstate.New(stateRepo, nil),
		Evolution:    evolution.New(evolutionRepo, nil),
		Builder:      contextbuilder.New(memoryRepo, metrics),
		Generator:    draftgen.New(nil),
		Drafts:       draftRepo,
		Memories:     memoryRepo,
		Publications: pubRepo,
		DecisionRepo: decisionRepo,
		Queue:        queue,
		Metrics:      metrics,
		Logger:       logger,
	})

	// ---- consumer loop ----
	go func() {
		err := consumer.Run(ctx, func(ctx context.Context, env trend.Envelope) error {
			_, err := pipe.HandleTrend(ctx, env)
			return err
		})
		if err != nil && !errors.Is(err, context.Canceled) {
			logger.Error().Err(err).Msg("trend_consumer_stopped")
		}
	}()

	// ---- publish worker ----
	//
	// The READ side of the publishing queues. Without it the queues grow
	// and nothing is ever published; with the publisher disabled there is
	// nothing to run, and the drafts accumulate on purpose (they are the
	// backlog the console shows).
	if pubEngine != nil {
		worker := publishworker.New(agentRepo, queue, pubEngine,
			time.Duration(settings.QueueDepthPollSeconds)*time.Second, logger)
		go worker.Run(ctx)
		logger.Info().Msg("publish_worker_started")
	} else {
		logger.Info().Msg("publish_worker_not_started_publisher_disabled")
	}

	// ---- queue depth gauge poller ----
	go func() {
		ticker := time.NewTicker(time.Duration(settings.QueueDepthPollSeconds) * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				agents, err := agentRepo.List(ctx)
				if err != nil {
					logger.Warn().Err(err).Msg("queue_depth_agents_list_failed")
					continue
				}
				for _, a := range agents {
					depth, err := queue.Depth(ctx, a.QueueName())
					if err != nil {
						continue
					}
					metrics.SetQueueDepth(a.Name, depth)
				}
			}
		}
	}()

	// ---- http (admin + health + metrics) ----
	startedAt := time.Now()
	opsServer := ops.New(ops.Config{
		ServiceID:   "nexus",
		ServiceName: "Insight Nexus",
		ServiceType: operationsv1.ServiceType_SERVICE_TYPE_PUBLICATION,
		Version:     settings.Version,
		Environment: os.Getenv("INSIGHT_ENVIRONMENT"),
		Tags:        []string{"agents", "publication", "llm", "audit"},
		StartedAt:   startedAt,
		Ready: func(ctx context.Context) error {
			return pool.Ping(ctx)
		},
		ActiveJobs: func(ctx context.Context) uint64 {
			agents, err := agentRepo.List(ctx)
			if err != nil {
				return 0
			}
			var total uint64
			for _, a := range agents {
				depth, err := queue.Depth(ctx, a.QueueName())
				if err == nil && depth > 0 {
					total += uint64(depth)
				}
			}
			return total
		},
		Capabilities: []*operationsv1.Capability{
			ops.Capability("agent_post", "Builds and queues agent publication drafts."),
			ops.Capability("summarization", "Uses LLM providers to generate concise content drafts."),
			ops.Capability("classification", "Routes trends to personas and publication decisions."),
			ops.CapabilityEnabled("publication",
				"Publishes controlled agent posts to Social.", pubEngine != nil),
			ops.Capability("metrics_generation", "Publishes publication and queue metrics."),
		},
	})
	apiHandler := httpapi.Routes(agentRepo, httpapi.AuditDeps{
		States:    stateRepo,
		Decisions: decisionRepo,
		Clusters:  clusterRepo,
		Evolution: evolutionRepo,
		Health:    healthEngine,
	}, httpapi.PublicationDeps{
		Candidates: candidateRepo,
		Tickets:    ticketRepo,
		Health:     healthMgr,
	}, httpapi.ConsoleOpsDeps{
		Tickets:                    ticketRepo,
		Personas:                   personaRepo,
		Audit:                      postgres.NewAuditRepo(pool),
		Publisher:                  pubEngine,
		PublisherUnavailableReason: pubUnavailableReason,
		DLQ:                        redisstream.DLQOpsFromConsumer(consumer),
	}, httpapi.AuthConfig{
		ControlPlaneToken: settings.ControlPlaneToken,
		IdentityURL:       settings.GatewayIdentityURL,
	}, observability.Handler(), logger)
	// Say which authority guards the admin API, at boot. The previous
	// behaviour — a 503 body naming an unset variable — was only visible
	// to whoever happened to call an endpoint.
	switch {
	case settings.ControlPlaneToken != "":
		logger.Info().Str("authority", "control-plane").Msg("admin_api_unlocked")
	case settings.GatewayIdentityURL != "":
		logger.Warn().Str("authority", "gateway").
			Msg("admin_api_unlocked_via_legacy_gateway_identity")
	default:
		logger.Warn().Msg("admin_api_locked_no_identity_authority_configured")
	}
	handler := http.NewServeMux()
	handler.Handle("/", apiHandler)
	handler.Handle("GET /healthz", opsServer.Routes())
	handler.Handle("GET /status", opsServer.Routes())
	handler.Handle("GET /capabilities", opsServer.Routes())
	handler.Handle("GET /metrics/summary", opsServer.Routes())
	server := &http.Server{
		Addr:              settings.HTTPAddr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		logger.Info().Str("addr", settings.HTTPAddr).Msg("http_listen")
		if err := server.ListenAndServe(); err != nil &&
			!errors.Is(err, http.ErrServerClosed) {
			logger.Fatal().Err(err).Msg("http_failed")
		}
	}()
	grpcAddr := os.Getenv("OPERATIONS_GRPC_ADDR")
	if grpcAddr == "" {
		grpcAddr = ":9090"
	}
	grpcServer := grpc.NewServer()
	operationsv1.RegisterOperationsServiceServer(grpcServer, opsServer)
	grpcListener, err := net.Listen("tcp", grpcAddr)
	if err != nil {
		logger.Fatal().Err(err).Str("addr", grpcAddr).Msg("operations_grpc_listen_failed")
	}
	go func() {
		logger.Info().Str("addr", grpcAddr).Msg("operations_grpc_listen")
		if err := grpcServer.Serve(grpcListener); err != nil {
			logger.Fatal().Err(err).Msg("operations_grpc_failed")
		}
	}()

	// ---- graceful shutdown ----
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	logger.Info().Msg("shutdown_start")
	cancel()
	shutdownCtx, scancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer scancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("http_shutdown_failed")
	}
	grpcServer.GracefulStop()
	logger.Info().Msg("shutdown_complete")
}
