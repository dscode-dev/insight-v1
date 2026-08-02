// Hello-world Insight Go service. Demonstrates the standard wiring:
// logging + tracing + metrics + health + middleware + graceful shutdown.
//
// Used as the smoke test for the foundation (W0.7 in the migration plan)
// and as the template that the service scaffolder copies into new
// service repos.
package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/konoha-labs/insight-runtime-go/pkg/config"
	"github.com/konoha-labs/insight-runtime-go/pkg/health"
	"github.com/konoha-labs/insight-runtime-go/pkg/logging"
	"github.com/konoha-labs/insight-runtime-go/pkg/metrics"
	"github.com/konoha-labs/insight-runtime-go/pkg/middleware"
	"github.com/konoha-labs/insight-runtime-go/pkg/tracing"
)

func main() {
	// ---- config ----
	service := config.String("INSIGHT_SERVICE", "hello-world")
	version := config.String("INSIGHT_VERSION", "dev")
	httpAddr := config.String("HTTP_ADDR", ":8080")
	otlpEndpoint := config.String("INSIGHT_OTLP_ENDPOINT", "")
	logLevel := config.String("LOG_LEVEL", "info")
	pretty := config.Bool("LOG_PRETTY", false)

	// ---- logging ----
	logger := logging.Init(logging.Config{
		Service: service,
		Version: version,
		Level:   logLevel,
		Pretty:  pretty,
	})

	// ---- tracing ----
	ctx := context.Background()
	shutdownTrace, err := tracing.Init(ctx, tracing.Config{
		Service:      service,
		Version:      version,
		OTLPEndpoint: otlpEndpoint,
		SampleRatio:  1.0,
	})
	if err != nil {
		logger.Fatal().Err(err).Msg("tracing_init_failed")
	}

	// ---- metrics + health ----
	m := metrics.New()
	hc := health.New()

	// ---- http handlers ----
	mux := http.NewServeMux()
	mux.Handle("/metrics", m.Handler)
	mux.Handle("/healthz", hc.Liveness())
	mux.Handle("/readyz", hc.Readiness())
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// Demonstrate the contextual logger picking up request_id + trace.
		logger := logging.FromContext(r.Context())
		logger.Info().Msg("hello_request")
		_, _ = w.Write([]byte("hello from " + service + "\n"))
	})

	handler := middleware.Recovery()(
		middleware.RequestID()(
			middleware.BodyLimit(1 << 20)( // 1 MiB default
				middleware.SecurityHeaders(middleware.SecurityHeadersConfig{
					EnableHSTS: false, // lab; production overlay flips this
				})(mux),
			),
		),
	)

	server := &http.Server{
		Addr:              httpAddr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		logger.Info().Str("addr", httpAddr).Msg("http_listen")
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Fatal().Err(err).Msg("http_failed")
		}
	}()

	// ---- graceful shutdown ----
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	logger.Info().Msg("shutdown_start")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("http_shutdown_failed")
	}
	if err := shutdownTrace(shutdownCtx); err != nil {
		logger.Error().Err(err).Msg("trace_shutdown_failed")
	}
	logger.Info().Msg("shutdown_complete")
}
