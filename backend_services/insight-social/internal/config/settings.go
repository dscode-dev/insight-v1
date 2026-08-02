// Package config holds the typed Settings + env parser.
//
// W2.0 scope: only the gRPC server + Postgres + Redis knobs are
// consumed. Aggregate-specific knobs (e.g. HumanSignal stream prefix,
// reputation tuning) land alongside their implementations in W2.1.
package config

import (
	"fmt"

	rtconfig "github.com/konoha-labs/insight-runtime-go/pkg/config"
)

type Settings struct {
	// --- Service identity ---
	Service string // INSIGHT_SERVICE
	Version string // INSIGHT_VERSION (build SHA, set at image build time)

	// --- gRPC server ---
	GrpcAddr        string // GRPC_ADDR (default :50051)
	MaxRecvMsgBytes int    // GRPC_MAX_RECV_MSG_BYTES (default 4 MiB)

	// --- Health/metrics HTTP listener ---
	// gRPC services don't naturally serve HTTP — we run a separate
	// listener (default :8080) for /healthz, /readyz, /metrics so
	// kube probes + Prometheus scrape with their usual conventions.
	HTTPAddr string // HTTP_ADDR (default :8080)
	OpsToken string // SOCIAL_OPS_TOKEN

	// --- Postgres (insight_social — schema owned by this service) ---
	DatabaseURL         string // DATABASE_URL
	DatabasePoolSize    int    // DATABASE_POOL_SIZE (default 10)
	DatabaseMaxOverflow int    // DATABASE_MAX_OVERFLOW (default 20)
	AutoApplyMigrations bool   // AUTO_APPLY_MIGRATIONS (false in prod; true in lab)

	// --- Redis (HumanSignal publisher target — used by W2.1 Signal service) ---
	RedisURL                string // REDIS_URL
	HumanSignalStreamPrefix string // HUMAN_SIGNAL_STREAM_PREFIX (default insight:stream:human_signal)
	StreamPartitions        int    // STREAM_PARTITIONS (default 8)

	// --- TLS (mTLS for gRPC server) ---
	// In prod the cert + key + CA bundle are mounted at
	// /var/run/secrets/tls/ by cert-manager via the Certificate
	// resource. Empty in lab → server uses plaintext (acceptable
	// because lab is single-tenant + NetworkPolicy-isolated).
	TLSCertPath string // TLS_CERT_PATH
	TLSKeyPath  string // TLS_KEY_PATH
	TLSCAPath   string // TLS_CA_PATH

	// --- Observability ---
	LogLevel        string  // LOG_LEVEL (debug|info|warn|error)
	LogPretty       bool    // LOG_PRETTY (lab only)
	OTLPEndpoint    string  // INSIGHT_OTLP_ENDPOINT (empty disables tracing)
	OTLPSampleRatio float64 // INSIGHT_OTLP_SAMPLE_RATIO (default 1.0; collector trims)
}

func Load() (*Settings, error) {
	s := &Settings{
		Service:             rtconfig.String("INSIGHT_SERVICE", "insight-social"),
		Version:             rtconfig.String("INSIGHT_VERSION", "dev"),
		GrpcAddr:            rtconfig.String("GRPC_ADDR", ":50051"),
		HTTPAddr:            rtconfig.String("HTTP_ADDR", ":8080"),
		OpsToken:            rtconfig.String("SOCIAL_OPS_TOKEN", ""),
		DatabaseURL:         rtconfig.MustString("DATABASE_URL"),
		RedisURL:            rtconfig.MustString("REDIS_URL"),
		AutoApplyMigrations: rtconfig.Bool("AUTO_APPLY_MIGRATIONS", false),
		HumanSignalStreamPrefix: rtconfig.String("HUMAN_SIGNAL_STREAM_PREFIX",
			"insight:stream:human_signal"),
		TLSCertPath:  rtconfig.String("TLS_CERT_PATH", ""),
		TLSKeyPath:   rtconfig.String("TLS_KEY_PATH", ""),
		TLSCAPath:    rtconfig.String("TLS_CA_PATH", ""),
		LogLevel:     rtconfig.String("LOG_LEVEL", "info"),
		LogPretty:    rtconfig.Bool("LOG_PRETTY", false),
		OTLPEndpoint: rtconfig.String("INSIGHT_OTLP_ENDPOINT", ""),
	}
	var err error
	if s.MaxRecvMsgBytes, err = rtconfig.Int("GRPC_MAX_RECV_MSG_BYTES", 4<<20); err != nil {
		return nil, fmt.Errorf("GRPC_MAX_RECV_MSG_BYTES: %w", err)
	}
	if s.DatabasePoolSize, err = rtconfig.Int("DATABASE_POOL_SIZE", 10); err != nil {
		return nil, fmt.Errorf("DATABASE_POOL_SIZE: %w", err)
	}
	if s.DatabaseMaxOverflow, err = rtconfig.Int("DATABASE_MAX_OVERFLOW", 20); err != nil {
		return nil, fmt.Errorf("DATABASE_MAX_OVERFLOW: %w", err)
	}
	if s.StreamPartitions, err = rtconfig.Int("STREAM_PARTITIONS", 8); err != nil {
		return nil, fmt.Errorf("STREAM_PARTITIONS: %w", err)
	}
	if s.OTLPSampleRatio, err = rtconfig.Float("INSIGHT_OTLP_SAMPLE_RATIO", 1.0); err != nil {
		return nil, fmt.Errorf("INSIGHT_OTLP_SAMPLE_RATIO: %w", err)
	}
	return s, nil
}
