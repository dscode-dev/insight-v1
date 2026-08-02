// Package logging provides the project-wide zerolog setup.
//
// All Insight Go services log JSON to stdout with a fixed schema:
//
//	{
//	  "time":       <RFC3339 UTC>,
//	  "level":      <debug|info|warn|error|fatal>,
//	  "service":    <service-name from env INSIGHT_SERVICE>,
//	  "version":    <build version from env INSIGHT_VERSION>,
//	  "request_id": <set by middleware.RequestID when present>,
//	  "trace_id":   <OTel trace id, set automatically when ctx carries one>,
//	  "span_id":    <OTel span id>,
//	  "event":      <short_snake_case>,
//	  ...callsite fields...
//	}
//
// The schema is enforced by passing structured fields rather than
// pre-formatted strings; everything downstream (Loki, ES, OTel
// Collector) parses on `event` + `service`.
package logging

import (
	"context"
	"io"
	"os"
	"strings"
	"time"

	"github.com/rs/zerolog"
	"go.opentelemetry.io/otel/trace"
)

// Config controls the boot-time logger setup. Most call sites pull
// values from env and pass through.
type Config struct {
	Service string
	Version string
	Level   string // "debug" | "info" | "warn" | "error"
	// Pretty turns on the human-readable ConsoleWriter — only for local
	// dev. In containers always leave it false so logs stay JSON.
	Pretty bool
}

// Init configures the global zerolog logger and returns the resulting
// logger. Callers that want per-component sub-loggers can derive
// `.With().Str("component", "...").Logger()`.
//
// Idempotent — calling twice with different configs swaps the global.
func Init(cfg Config) zerolog.Logger {
	zerolog.TimeFieldFormat = time.RFC3339
	zerolog.LevelFieldName = "level"
	zerolog.MessageFieldName = "event"
	zerolog.TimestampFieldName = "time"

	var out io.Writer = os.Stdout
	if cfg.Pretty {
		out = zerolog.ConsoleWriter{Out: os.Stdout, TimeFormat: time.Kitchen}
	}

	lvl, err := zerolog.ParseLevel(strings.ToLower(cfg.Level))
	if err != nil || cfg.Level == "" {
		lvl = zerolog.InfoLevel
	}

	logger := zerolog.New(out).
		Level(lvl).
		With().
		Timestamp().
		Str("service", cfg.Service).
		Str("version", cfg.Version).
		Logger()

	zerolog.DefaultContextLogger = &logger
	return logger
}

// FromContext returns the zerolog logger carried by ctx, falling back
// to the global default. The returned logger has trace_id and span_id
// prefilled when ctx carries an active OTel span.
//
// Most call sites should use this rather than `zerolog.Ctx(ctx)`
// directly so trace correlation always lands in the log line.
func FromContext(ctx context.Context) zerolog.Logger {
	base := *zerolog.Ctx(ctx)
	if span := trace.SpanFromContext(ctx); span.SpanContext().IsValid() {
		sc := span.SpanContext()
		base = base.With().
			Str("trace_id", sc.TraceID().String()).
			Str("span_id", sc.SpanID().String()).
			Logger()
	}
	return base
}
