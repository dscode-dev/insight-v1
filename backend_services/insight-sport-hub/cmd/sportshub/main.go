// insight-sports-hub — composition root.
//
// Sprint 1: foundation only. Boots Postgres + the HTTP observability
// surface + wires every application service into the
// IngestionOrchestrator. NO external adapters yet — the orchestrator
// is dormant until Sprint 2 attaches the provider crawlers + Redis
// publisher.
package main

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	appbudget "github.com/konoha-labs/insight-sports-hub/internal/application/budget"
	appcanon "github.com/konoha-labs/insight-sports-hub/internal/application/canonicalization"
	appconfidence "github.com/konoha-labs/insight-sports-hub/internal/application/confidence"
	appconflict "github.com/konoha-labs/insight-sports-hub/internal/application/conflict"
	appidentity "github.com/konoha-labs/insight-sports-hub/internal/application/identity"
	appingestion "github.com/konoha-labs/insight-sports-hub/internal/application/ingestion"
	appjobrunner "github.com/konoha-labs/insight-sports-hub/internal/application/jobrunner"
	appnorm "github.com/konoha-labs/insight-sports-hub/internal/application/normalization"
	appoddschange "github.com/konoha-labs/insight-sports-hub/internal/application/oddschange"
	appoddsmode "github.com/konoha-labs/insight-sports-hub/internal/application/oddsmode"
	apppub "github.com/konoha-labs/insight-sports-hub/internal/application/publishing"
	appratelimit "github.com/konoha-labs/insight-sports-hub/internal/application/ratelimit"
	appsched "github.com/konoha-labs/insight-sports-hub/internal/application/scheduler"
	appscheduling "github.com/konoha-labs/insight-sports-hub/internal/application/scheduling"
	appsource "github.com/konoha-labs/insight-sports-hub/internal/application/source"
	appval "github.com/konoha-labs/insight-sports-hub/internal/application/validation"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/clock"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/httpapi"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/postgres"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/api_football"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/football_data"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/the_odds_api"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/publishing"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/queue"
	queueredis "github.com/konoha-labs/insight-sports-hub/internal/adapters/queue/redis"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/redisinfra"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	ops "github.com/konoha-labs/insight-sports-hub/internal/operations"

	"github.com/konoha-labs/insight-sports-hub/internal/config"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"

	operationsv1 "github.com/konoha-labs/insight-protos/gen/go/operations/v1"
	"github.com/konoha-labs/insight-runtime-go/pkg/health"
	"github.com/konoha-labs/insight-runtime-go/pkg/logging"
	"github.com/konoha-labs/insight-runtime-go/pkg/metrics"
	"github.com/konoha-labs/insight-runtime-go/pkg/tracing"
	"google.golang.org/grpc"
)

func main() {
	settings, err := config.Load()
	if err != nil {
		// Logger isn't up yet.
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

	// ---- repositories ----
	sourceRepo := postgres.NewSourceRepo(pgPool)
	rawRepo := postgres.NewRawEventRepo(pgPool)
	canonRepo := postgres.NewCanonicalEventRepo(pgPool)
	lineageRepo := postgres.NewLineageRepo(pgPool)
	// Sprint 2 — Postgres-backed CompetitionRegistry replaces the
	// permissive in-memory adapter from Sprint 1.
	compRegistry := postgres.NewCompetitionRepo(pgPool)

	// ---- observability ports ----
	m := metrics.New()
	metricsAdapter := observability.NewNoopMetrics() // Sprint 3+ wires Prometheus
	providerStatus := observability.NewProviderStatus()

	// ---- supporting adapters ----
	clockAdapter := clock.System_()
	// Sprint 5 — publisher selection. When REDIS_PUBLISHER_ENABLED
	// is set we wire the real Redis Streams publisher Atlas consumes
	// from; otherwise fall back to the noop (lab/dev).
	publisher := selectPublisher(ctx, settings, logger)

	// Sprint 6.1 — odds production hardening: change-detection publish
	// gate, response cache, budget manager, dynamic-polling advisor +
	// kickoff tracker, runtime mode controller. Redis-backed when
	// available; in-memory fallback otherwise (single-instance/dev).
	oddsHard := buildOddsHardening(ctx, settings, clockAdapter, logger)
	defer oddsHard.Close()

	// ---- application services ----
	sourceSvc := appsource.New(sourceRepo, metricsAdapter)

	normalizerSvc := appnorm.New()
	validationSvc := appval.New(
		rawRepo, compRegistry, clockAdapter, metricsAdapter,
		appval.Config{FutureSkew: settings.FutureSkew},
	)
	confidenceSvc := appconfidence.New(appconfidence.NewWeightedAveragePolicy())
	conflictStrategy := appconflict.NewFieldEqualityStrategy()
	conflictSvc := appconflict.New(conflictStrategy, metricsAdapter.IncConflict)
	canonicalizationSvc := appcanon.New()
	// Sprint 6.2 — cross-provider canonical match identity. The Hub
	// stamps a best-effort canonical_match_id onto every canonical
	// event (deterministic mint keeps it reproducible across pods);
	// Atlas owns the authoritative persistent registry.
	identityResolver := appidentity.NewResolver(appidentity.NewMemoryRegistry(), settings.IdentityKickoffTolerance)
	// Sprint 6.1 — install the odds change-detection gate so sub-
	// threshold odds ticks are suppressed from the stream (Atlas stays
	// fed with meaningful moves only). Non-odds events pass untouched.
	publishingSvc := apppub.New(publisher, apppub.WithGate(oddsHard.Gate))

	orchestrator := appingestion.New(appingestion.Deps{
		Normalizer:               normalizerSvc,
		Validation:               validationSvc,
		Canonicalization:         canonicalizationSvc,
		ConflictDetection:        conflictSvc,
		Confidence:               confidenceSvc,
		Publishing:               publishingSvc,
		RawEventRepository:       rawRepo,
		CanonicalEventRepository: canonRepo,
		LineageRepository:        lineageRepo,
		SourceRepository:         sourceRepo,
		Metrics:                  metricsAdapter,
		IdentityResolver:         identityResolver,
	})

	// ---- provider adapters (Sprint 2) ----
	// Sprint 6.1 — the_odds_api receives its cache + budget recorder +
	// kickoff observer here.
	adapters := buildProviderAdapters(
		settings, compRegistry, providerStatus, logger, oddsHard.AdapterOptions(),
	)
	registerProviderSources(ctx, sourceSvc, adapters, logger)
	// Sprint 2.1 — stamp the static profile (capabilities, rate
	// policy, poll policies) onto the status tracker so the
	// /v1/providers/status response surfaces them.
	registerProviderProfiles(adapters, providerStatus)
	registeredSourceIDs := make([]string, 0, len(adapters))
	adapterMap := make(map[string]ports.SourceAdapter, len(adapters))
	for _, a := range adapters {
		id := a.Identity().SourceID
		registeredSourceIDs = append(registeredSourceIDs, id)
		adapterMap[id] = a
	}

	// ---- Sprint 5.1: dead-letter store (Postgres) ----
	// Replaces Sprint 4's NoopDLQ. The queue adapter writes via
	// ports.DeadLetterStore (Record); the HTTP handler reads via
	// ports.DeadLetterReader (List/Get/MarkReplayed).
	dlqRepo := postgres.NewDeadLetterRepo(pgPool)

	// ---- Sprint 3 + 4: scheduler / queue / runner / rate limiter ----
	// Sprint 4 — queue backend selection. The application layer
	// only knows about ports.JobQueue; this is the only place that
	// touches a concrete impl.
	var dlq ports.DeadLetterStore = dlqRepo
	jobQueue, queueStats, queueClose, qerr := buildJobQueue(ctx, settings, dlq, logger)
	if qerr != nil {
		logger.Fatal().Err(qerr).Msg("queue_backend_init_failed")
	}
	defer queueClose()
	limiter := appratelimit.NewSliding(clockAdapter)
	configureRatePolicies(adapters, limiter)
	pollPolicies := collectPollPolicies(adapters)

	planner := appsched.NewPlanner(adapterMap, compRegistry, pollPolicies, clockAdapter)
	// Sprint 6.1 — install the dynamic scheduling advisor (kickoff
	// proximity + budget pressure + operational mode).
	planner.SetAdvisor(oddsHard.Advisor)
	dispatcher := appsched.NewDispatcher(jobQueue, providerStatus, logger)
	scheduler := appsched.New(
		appsched.Config{Interval: settings.SchedulerInterval},
		planner, dispatcher, logger,
	)
	runner := appjobrunner.New(
		appjobrunner.Config{Workers: settings.JobRunnerWorkers},
		jobQueue, adapterMap, limiter,
		func(ctx context.Context, raw *event.RawSportsEvent) error {
			_, err := orchestrator.IngestRaw(ctx, raw)
			return err
		},
		providerStatus, logger,
	)

	// ---- health ----
	hc := health.New()
	hc.AddReadiness("postgres", func(ctx context.Context) error {
		return pgPool.Ping(ctx)
	})
	startedAt := time.Now()
	opsServer := ops.New(ops.Config{
		ServiceID:   "sport_hub",
		ServiceName: "Sport Hub",
		ServiceType: operationsv1.ServiceType_SERVICE_TYPE_DATA_INGESTION,
		Version:     settings.Version,
		Environment: os.Getenv("INSIGHT_ENVIRONMENT"),
		Tags:        []string{"sports", "ingestion", "scheduler", "signals"},
		StartedAt:   startedAt,
		Ready: func(ctx context.Context) error {
			return pgPool.Ping(ctx)
		},
		ActiveJobs: func(ctx context.Context) uint64 {
			if queueStats == nil {
				return 0
			}
			stats := queueStats.Stats(ctx)
			active := stats.PendingMessages + stats.RetryQueueSize
			if active < 0 {
				return 0
			}
			return uint64(active)
		},
		Capabilities: []*operationsv1.Capability{
			ops.Capability("sports_ingestion", "Collects sports fixtures, odds and provider data."),
			ops.Capability("match_processing", "Normalizes and canonicalizes match events."),
			ops.Capability("metrics_generation", "Publishes operational ingestion metrics."),
			ops.Capability("community_signals", "Publishes canonical events consumed by downstream intelligence services."),
			ops.Capability("scheduler", "Schedules provider polling jobs."),
			ops.Capability("dlq", "Exposes dead-letter queue visibility and replay contracts."),
		},
	})

	// ---- start scheduler + runner ----
	// Both share the parent ctx so a single cancel reaches both. The
	// runner Run() blocks until the queue is closed AND its workers
	// drain; the scheduler Run() blocks until ctx is cancelled.
	var schedRunner sync.WaitGroup
	if len(adapters) > 0 {
		schedRunner.Add(2)
		go func() {
			defer schedRunner.Done()
			_ = scheduler.Run(ctx)
		}()
		go func() {
			defer schedRunner.Done()
			runner.Run(ctx)
		}()
	} else {
		logger.Warn().Msg("scheduler_inactive_no_providers_configured")
	}

	// ---- http server ----
	apiHandler := httpapi.Routes(httpapi.RoutesConfig{
		Health:          hc,
		MetricsHandler:  m.Handler,
		ProvidersStatus: httpapi.ProvidersStatusHandler(providerStatus, registeredSourceIDs),
		SchedulerStatus: httpapi.SchedulerStatusHandler(httpapi.SchedulerStatusConfig{
			Scheduler:           scheduler,
			Queue:               jobQueue,
			QueueStats:          queueStats,
			Workers:             settings.JobRunnerWorkers,
			RegisteredProviders: registeredSourceIDs,
			Competitions:        compRegistry,
			NextJobsLimit:       20,
		}),
		// Sprint 5.1 — DLQ admin surface.
		DLQList: httpapi.DLQListHandler(httpapi.DLQConfig{
			Reader: dlqRepo, Enqueuer: jobQueue,
		}),
		DLQGet: httpapi.DLQGetHandler(httpapi.DLQConfig{
			Reader: dlqRepo, Enqueuer: jobQueue,
		}),
		DLQReplay: httpapi.DLQReplayHandler(httpapi.DLQConfig{
			Reader: dlqRepo, Enqueuer: jobQueue,
		}),
		DLQToken: settings.OpsToken,
	})
	handler := http.NewServeMux()
	handler.Handle("/", apiHandler)
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
		grpcAddr = ":9080"
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

	// Sprint 3/4 shutdown order:
	//   1. cancel ctx → scheduler stops producing.
	//   2. close jobQueue → runner workers unblock from Dequeue,
	//      finish their in-flight job (ack/retry/fail still work
	//      against the live queue until Close returns), then exit.
	//   3. wait for scheduler+runner goroutines (bounded).
	//   4. http Shutdown drains in-flight HTTP requests.
	cancel()
	queueClose()
	shutdownCtx, scancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer scancel()

	done := make(chan struct{})
	go func() {
		schedRunner.Wait()
		close(done)
	}()
	select {
	case <-done:
		logger.Info().Msg("scheduler_runner_drained")
	case <-shutdownCtx.Done():
		logger.Warn().Msg("scheduler_runner_shutdown_timeout")
	}

	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("http_shutdown_failed")
	}
	grpcServer.GracefulStop()
	if err := shutdownTrace(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("trace_shutdown_failed")
	}
	logger.Info().Msg("shutdown_complete")
}

// ---------------------------------------------------------------------------
// Sprint 5 — publisher selection.
// ---------------------------------------------------------------------------

// selectPublisher returns the configured ports.Publisher. When the
// PUBLISHER_BACKEND env is "redis" we wire the real Redis Streams
// publisher Atlas + downstream consumers read from. Falls back to
// the noop for local development without Redis.
//
// Architectural rule: composition root is the ONLY place a concrete
// publisher impl is chosen. PublishingService never sees Redis.
func selectPublisher(
	ctx context.Context,
	settings *config.Settings,
	logger zerolog.Logger,
) ports.Publisher {
	if settings.PublisherBackend != "redis" {
		logger.Info().Str("backend", "noop").Msg("publisher_backend_initialised")
		return publishing.NewNoop()
	}
	pub, err := publishing.NewRedis(ctx, publishing.RedisConfig{
		Addr:        settings.RedisAddr,
		Password:    settings.RedisPassword,
		DB:          settings.RedisDB,
		StreamMatch: settings.PublisherStreamMatch,
		StreamOdds:  settings.PublisherStreamOdds,
		StreamCtx:   settings.PublisherStreamCtx,
		MaxLen:      settings.PublisherMaxLen,
	}, logger)
	if err != nil {
		logger.Error().Err(err).
			Msg("publisher_redis_init_failed_fallback_noop")
		return publishing.NewNoop()
	}
	logger.Info().Str("backend", "redis").Msg("publisher_backend_initialised")
	return pub
}

// ---------------------------------------------------------------------------
// Sprint 4 — queue backend selection.
// ---------------------------------------------------------------------------

// buildJobQueue constructs the configured ports.JobQueue. Returns
// the queue itself, an optional ports.StatsReporter (the queue may
// also implement Stats), and a Close hook the composition root uses
// at shutdown.
//
// Architectural rule: this helper lives in cmd/, not in application/.
// The composition root is the ONLY place a concrete queue impl is
// chosen.
func buildJobQueue(
	ctx context.Context,
	settings *config.Settings,
	dlq ports.DeadLetterStore,
	logger zerolog.Logger,
) (ports.JobQueue, ports.StatsReporter, func(), error) {
	switch settings.QueueBackend {
	case "redis":
		consumerName := settings.RedisConsumer
		if consumerName == "" {
			hostname, _ := os.Hostname()
			consumerName = fmt.Sprintf("%s-%d", hostname, os.Getpid())
		}
		q, err := queueredis.New(ctx, queueredis.Config{
			Addr:         settings.RedisAddr,
			Password:     settings.RedisPassword,
			DB:           settings.RedisDB,
			Stream:       settings.RedisStream,
			Group:        settings.RedisGroup,
			ConsumerName: consumerName,
			RetryZSet:    settings.RedisRetryZSet,
			MaxLen:       settings.RedisMaxLen,
			Claimer: queueredis.ClaimerConfig{
				Enabled:       settings.ClaimerEnabled,
				MinIdleTime:   time.Duration(settings.ClaimerMinIdleSeconds) * time.Second,
				Interval:      time.Duration(settings.ClaimerIntervalSec) * time.Second,
				MaxDeliveries: int64(settings.ClaimerMaxDeliveries),
			},
		}, dlq, logger)
		if err != nil {
			return nil, nil, func() {}, err
		}
		logger.Info().
			Str("backend", "redis").
			Str("stream", settings.RedisStream).
			Msg("queue_backend_initialised")
		return q, q, q.Close, nil
	default:
		// In-memory — Sprint 3 default. Dev / lab / tests.
		q := queue.NewInMemory(queue.InMemoryConfig{
			Capacity: settings.SchedulerQueueCapacity,
			DLQ:      dlq,
			Logger:   logger,
		})
		logger.Info().
			Str("backend", "inmemory").
			Int("capacity", settings.SchedulerQueueCapacity).
			Msg("queue_backend_initialised")
		return q, q, q.Close, nil
	}
}

// ---------------------------------------------------------------------------
// Sprint 3 boot helpers — rate-limit configuration + poll policy fan-out.
// ---------------------------------------------------------------------------

// configureRatePolicies — push each adapter's default rate envelope
// into the limiter. The values mirror the Sprint 2.1 status-profile
// seeds (free-tier envelopes). Sprint 4+ will read these from a
// `rate_policies` table instead.
func configureRatePolicies(adapters []ports.SourceAdapter, limiter *appratelimit.SlidingLimiter) {
	for _, a := range adapters {
		sourceID := a.Identity().SourceID
		limiter.SetPolicy(defaultRatePolicy(sourceID))
	}
}

// collectPollPolicies — group default poll policies by SourceID for
// the Planner. The Planner consults this map per provider; adapters
// never see it.
func collectPollPolicies(adapters []ports.SourceAdapter) map[string][]syncdom.PollPolicy {
	out := make(map[string][]syncdom.PollPolicy, len(adapters))
	for _, a := range adapters {
		sourceID := a.Identity().SourceID
		out[sourceID] = defaultPollPolicies(sourceID)
	}
	return out
}

// ---------------------------------------------------------------------------
// Provider boot helpers — Sprint 2.
// ---------------------------------------------------------------------------

// buildProviderAdapters constructs the configured provider adapters.
// An adapter is built ONLY when its API key is present in the env —
// missing keys yield a logged warning + the adapter is omitted from
// the registered set. This keeps the local-lab boot loop usable
// without holding production credentials.
func buildProviderAdapters(
	settings *config.Settings,
	registry ports.CompetitionRegistry,
	status observability.ProviderStatusRecorder,
	logger zerolog.Logger,
	oddsOpts []the_odds_api.Option,
) []ports.SourceAdapter {
	out := make([]ports.SourceAdapter, 0, 2)

	if settings.APIFootballKey != "" {
		out = append(out, api_football.New(
			api_football.AdapterConfig{
				APIKey:  settings.APIFootballKey,
				BaseURL: settings.APIFootballBaseURL,
			},
			registry, status,
		))
		logger.Info().
			Str("source_id", api_football.SourceID).
			Str("adapter_version", api_football.AdapterVersion).
			Msg("provider_adapter_built")
	} else {
		logger.Warn().
			Str("source_id", api_football.SourceID).
			Msg("provider_adapter_skipped_missing_key")
	}

	if settings.FootballDataKey != "" {
		out = append(out, football_data.New(
			football_data.AdapterConfig{
				APIKey:  settings.FootballDataKey,
				BaseURL: settings.FootballDataBaseURL,
			},
			registry, status,
		))
		logger.Info().
			Str("source_id", football_data.SourceID).
			Str("adapter_version", football_data.AdapterVersion).
			Msg("provider_adapter_built")
	} else {
		logger.Warn().
			Str("source_id", football_data.SourceID).
			Msg("provider_adapter_skipped_missing_key")
	}

	if settings.TheOddsAPIKey != "" {
		out = append(out, the_odds_api.New(
			the_odds_api.AdapterConfig{
				APIKey:  settings.TheOddsAPIKey,
				BaseURL: settings.TheOddsAPIBaseURL,
			},
			registry, status, oddsOpts...,
		))
		logger.Info().
			Str("source_id", the_odds_api.SourceID).
			Str("adapter_version", the_odds_api.AdapterVersion).
			Msg("provider_adapter_built")
	} else {
		logger.Warn().
			Str("source_id", the_odds_api.SourceID).
			Msg("provider_adapter_skipped_missing_key")
	}

	return out
}

// registerProviderProfiles — Sprint 2.1.
//
// Stamps each adapter's static profile (capabilities + rate policy +
// poll policies) onto the ProviderStatus tracker. The /v1/providers/status
// endpoint then surfaces them alongside the live counters.
//
// CONTRACTS ONLY: the rate policy and poll policies are NOT yet
// enforced or consumed by any scheduler — those land in Sprint 3.
// The values here are conservative defaults derived from each
// provider's documented free-tier envelope.
func registerProviderProfiles(
	adapters []ports.SourceAdapter,
	status observability.ProviderStatusRecorder,
) {
	for _, a := range adapters {
		id := a.Identity()
		profile := observability.Profile{
			Capabilities: id.Capabilities,
			RatePolicy:   defaultRatePolicy(id.SourceID),
			PollPolicies: defaultPollPolicies(id.SourceID),
		}
		status.RegisterProfile(id.SourceID, profile)
	}
}

// defaultRatePolicy — Sprint 2.1 contract seed. Numbers mirror each
// provider's documented free-tier envelope; not yet enforced.
func defaultRatePolicy(sourceID string) syncdom.RateLimitPolicy {
	switch sourceID {
	case api_football.SourceID:
		// API-Football free tier: 100 req/day, ~10 req/min sustained.
		p, _ := syncdom.NewRateLimitPolicy(sourceID, 10, 300, 100, 20)
		return p
	case football_data.SourceID:
		// football-data.org free tier: 10 req/min.
		p, _ := syncdom.NewRateLimitPolicy(sourceID, 10, 600, 0, 12)
		return p
	case the_odds_api.SourceID:
		// The Odds API free tier: 500 req/month. Keep a conservative
		// minute envelope; the monthly quota is the real constraint.
		p, _ := syncdom.NewRateLimitPolicy(sourceID, 5, 300, 500, 5)
		return p
	default:
		return syncdom.RateLimitPolicy{ProviderID: sourceID}
	}
}

// defaultPollPolicies — Sprint 2.1 contract seed. The Scheduler
// (Sprint 3) will load these; today they only render in the status
// response so admins can review the planned cadence.
func defaultPollPolicies(sourceID string) []syncdom.PollPolicy {
	switch sourceID {
	case api_football.SourceID:
		fixtures, _ := syncdom.NewPollPolicy(sourceID, syncdom.TypeFixtures, 30*time.Minute, 0, true)
		results, _ := syncdom.NewPollPolicy(sourceID, syncdom.TypeResults, 15*time.Minute, 15*time.Second, true)
		standings, _ := syncdom.NewPollPolicy(sourceID, syncdom.TypeStandings, 6*time.Hour, 0, true)
		return []syncdom.PollPolicy{fixtures, results, standings}
	case football_data.SourceID:
		fixtures, _ := syncdom.NewPollPolicy(sourceID, syncdom.TypeFixtures, 1*time.Hour, 0, true)
		results, _ := syncdom.NewPollPolicy(sourceID, syncdom.TypeResults, 30*time.Minute, 1*time.Minute, true)
		standings, _ := syncdom.NewPollPolicy(sourceID, syncdom.TypeStandings, 12*time.Hour, 0, true)
		return []syncdom.PollPolicy{fixtures, results, standings}
	case the_odds_api.SourceID:
		// Odds drift continuously; poll on a tight cadence and tighten
		// further when a fixture is live. The monthly quota is guarded
		// by the rate-limit policy, not the poll interval.
		odds, _ := syncdom.NewPollPolicy(sourceID, syncdom.TypeOdds, 5*time.Minute, 1*time.Minute, true)
		return []syncdom.PollPolicy{odds}
	default:
		return nil
	}
}

// registerProviderSources registers each adapter as a Source in the
// SourceRegistry. Idempotent — a re-registration of an existing
// source is a no-op (ErrDuplicate surfaces from the repo, swallowed
// here so re-deploys boot cleanly).
func registerProviderSources(
	ctx context.Context,
	svc *appsource.Service,
	adapters []ports.SourceAdapter,
	logger zerolog.Logger,
) {
	for _, a := range adapters {
		id := a.Identity()
		// The source.New constructor pins SourceID as the canonical
		// name — same value the SourceRef stamped on every event
		// references. SourceRegistry.Register uses a deterministic
		// UUIDv5 over the SourceID so re-creating across pods
		// converges on the same id.
		canonicalID := uuid.NewSHA1(
			uuid.MustParse("ab1d0fe5-3a4f-4a5f-9c0e-4d4d8e1a4f8d"),
			[]byte(id.SourceID),
		)
		src, err := source.New(
			canonicalID, id.SourceID, id.SourceType,
			100,  // default priority — admin tooling tunes later
			true, // enabled at registration
			id.ConfidenceWeight,
		)
		if err != nil {
			logger.Error().Err(err).
				Str("source_id", id.SourceID).
				Msg("source_construction_failed")
			continue
		}
		err = svc.Register(ctx, src)
		switch {
		case err == nil:
			logger.Info().
				Str("source_id", id.SourceID).
				Str("type", string(id.SourceType)).
				Float64("confidence_weight", id.ConfidenceWeight).
				Msg("source_registered")
		case errors.Is(err, ports.ErrDuplicate):
			logger.Debug().
				Str("source_id", id.SourceID).
				Msg("source_already_registered")
		default:
			logger.Error().Err(err).
				Str("source_id", id.SourceID).
				Msg("source_registration_failed")
		}
	}
}

// ---------------------------------------------------------------------------
// Sprint 6.1 — odds production hardening composition.
// ---------------------------------------------------------------------------

// oddsHardening bundles the Sprint 6.1 odds collaborators built at the
// composition root. The Gate plugs into publishing, the Advisor into
// the planner, and the adapter options carry the cache + budget
// recorder + kickoff observer to the_odds_api.
type oddsHardening struct {
	Gate     apppub.PublishGate
	Advisor  appsched.SchedulingAdvisor
	cache    the_odds_api.ResponseCache // nil when Redis unavailable
	recorder the_odds_api.RequestRecorder
	tracker  *appscheduling.KickoffTracker
	closeFn  func()
}

func (o oddsHardening) Close() {
	if o.closeFn != nil {
		o.closeFn()
	}
}

// AdapterOptions returns the the_odds_api options carrying the Sprint
// 6.1 collaborators. The cache is included only when present.
func (o oddsHardening) AdapterOptions() []the_odds_api.Option {
	opts := []the_odds_api.Option{
		the_odds_api.WithRequestRecorder(o.recorder),
		the_odds_api.WithScheduleObserver(o.tracker),
	}
	if o.cache != nil {
		opts = append(opts, the_odds_api.WithCache(o.cache))
	}
	return opts
}

// budgetRecorder adapts a *budget.Manager to the_odds_api.RequestRecorder.
type budgetRecorder struct{ mgr *appbudget.Manager }

func (b budgetRecorder) RecordRequest(ctx context.Context, _ string) {
	if err := b.mgr.Record(ctx); err != nil {
		// Best-effort accounting — never block a fetch on budget IO.
		_ = err
	}
}

// buildOddsHardening assembles the Sprint 6.1 components. Redis-backed
// stores are used when Redis is in play (queue or publisher on redis)
// and reachable; otherwise the in-memory fallbacks keep the feature
// working on a single instance / in dev.
func buildOddsHardening(
	ctx context.Context,
	settings *config.Settings,
	clk ports.Clock,
	logger zerolog.Logger,
) oddsHardening {
	var (
		counterStore appbudget.CounterStore      = appbudget.NewMemoryStore(clk.Now)
		lastStore    appoddschange.LastOddsStore = appoddschange.NewMemoryStore()
		modeSource   appoddsmode.Source          = appoddsmode.StaticSource{M: appoddsmode.Parse(settings.OddsMode)}
		cache        the_odds_api.ResponseCache
		closeFn      = func() {}
	)

	if settings.QueueBackend == "redis" || settings.PublisherBackend == "redis" {
		client, err := redisinfra.NewClient(ctx, settings.RedisAddr, settings.RedisPassword, settings.RedisDB, 5*time.Second)
		if err != nil {
			logger.Warn().Err(err).Msg("odds_hardening_redis_unavailable_using_memory")
		} else {
			cfg := redisinfra.Config{CacheTTL: settings.OddsCacheTTL}.Defaults()
			counterStore = redisinfra.NewBudgetStore(client)
			lastStore = redisinfra.NewLastOddsStore(client, cfg.LastPrefix)
			modeSource = redisinfra.NewModeSource(client, cfg.ModeKey)
			cache = redisinfra.NewOddsResponseCache(client, cfg.CacheTTL, cfg.CachePrefix)
			closeFn = func() { _ = client.Close() }
			logger.Info().Msg("odds_hardening_redis_initialised")
		}
	}

	caps := appbudget.Caps{
		Hourly:  settings.OddsBudgetHourly,
		Daily:   settings.OddsBudgetDaily,
		Monthly: settings.OddsBudgetMonthly,
	}
	budgetMgr := appbudget.NewManager(the_odds_api.SourceID, caps, counterStore, clk)

	gate := appoddschange.NewGate(settings.OddsChangeThresholdPercent, lastStore, 24*time.Hour)

	profiles := appoddsmode.DefaultProfiles()
	if settings.OddsWorldCupPollMultiplier > 0 {
		wc := profiles[appoddsmode.ModeWorldCup]
		wc.PollMultiplier = settings.OddsWorldCupPollMultiplier
		profiles[appoddsmode.ModeWorldCup] = wc
	}
	modeCtl := appoddsmode.NewController(
		modeSource, profiles, appoddsmode.Parse(settings.OddsMode), settings.OddsModeCacheTTL, clk,
	)

	tracker := appscheduling.NewKickoffTracker(clk, 3*time.Hour, 6*time.Hour)

	dyn, err := syncdom.NewDynamicPollPolicy(
		the_odds_api.SourceID, syncdom.TypeOdds,
		[]syncdom.PollWindow{
			{MaxLeadTime: 6 * time.Hour, Interval: settings.OddsPollWindow6h},
			{MaxLeadTime: 48 * time.Hour, Interval: settings.OddsPollWindow48h},
			{MaxLeadTime: 7 * 24 * time.Hour, Interval: settings.OddsPollWindow7d},
		},
		settings.OddsPollLive, settings.OddsPollDefault, true,
	)
	if err != nil {
		logger.Error().Err(err).Msg("odds_dynamic_policy_invalid_disabling_advisor")
	}

	advisor := appscheduling.NewOddsAdvisor(appscheduling.Config{
		DynamicPolicies: []syncdom.DynamicPollPolicy{dyn},
		Schedule:        tracker,
		Budgets:         map[string]appscheduling.BudgetController{the_odds_api.SourceID: budgetMgr},
		Mode:            modeCtl,
		Logger:          logger,
	})

	return oddsHardening{
		Gate:     gate,
		Advisor:  advisor,
		cache:    cache,
		recorder: budgetRecorder{mgr: budgetMgr},
		tracker:  tracker,
		closeFn:  closeFn,
	}
}
