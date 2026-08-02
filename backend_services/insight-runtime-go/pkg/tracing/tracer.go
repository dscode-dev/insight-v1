// Package tracing wires the OpenTelemetry SDK with the OTLP gRPC
// exporter. Off by default — set INSIGHT_OTLP_ENDPOINT to enable.
//
// Once Init returns, calling any of the global OTel APIs (`otel.Tracer`,
// the otelgrpc interceptors in this package) just works. Shutdown
// blocks up to 5 seconds for in-flight spans to flush.
package tracing

import (
	"context"
	"fmt"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
)

type Config struct {
	Service      string
	Version      string
	OTLPEndpoint string  // e.g. "otel-collector.observability.svc:4317"; empty disables
	SampleRatio  float64 // 0..1; 1.0 = always sample. Default 0.1 in prod.
}

// ShutdownFunc is called from main on graceful shutdown; flushes
// remaining spans to the collector.
type ShutdownFunc func(context.Context) error

// Init returns a no-op shutdown when tracing is disabled.
func Init(ctx context.Context, cfg Config) (ShutdownFunc, error) {
	if cfg.OTLPEndpoint == "" {
		return func(context.Context) error { return nil }, nil
	}

	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(cfg.OTLPEndpoint),
		// Local-network collector, no TLS at the OTel layer — mTLS
		// happens at the gRPC layer for inter-service. For OTel itself
		// we trust the cluster network policy.
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, fmt.Errorf("otlptracegrpc.New: %w", err)
	}

	res, err := resource.Merge(
		resource.Default(),
		resource.NewWithAttributes(
			semconv.SchemaURL,
			semconv.ServiceName(cfg.Service),
			semconv.ServiceVersion(cfg.Version),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("resource.Merge: %w", err)
	}

	ratio := cfg.SampleRatio
	if ratio <= 0 || ratio > 1 {
		ratio = 0.1
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter, sdktrace.WithBatchTimeout(5*time.Second)),
		sdktrace.WithResource(res),
		sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.TraceIDRatioBased(ratio))),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	return func(shutdownCtx context.Context) error {
		ctx, cancel := context.WithTimeout(shutdownCtx, 5*time.Second)
		defer cancel()
		return tp.Shutdown(ctx)
	}, nil
}
