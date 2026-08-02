// Package grpcclient builds gRPC client connections with the standard
// Insight stack:
//
//   - OpenTelemetry tracing (otelgrpc handler)
//   - mTLS via TLSConfig when provided
//   - keepalive tuned for in-cluster traffic (30s ping, 10s timeout)
//
// Services dial each other through a single client per remote, held
// in a long-lived pool inside the consumer.
package grpcclient

import (
	"crypto/tls"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/keepalive"
)

type Config struct {
	// Target is a DNS name or "host:port".
	Target string
	// TLSConfig enables mTLS to the server. Leave nil for plaintext.
	TLSConfig *tls.Config
}

// Dial returns a *grpc.ClientConn ready for use. Caller closes it on
// shutdown. Failure paths are surfaced as errors — no panics.
func Dial(cfg Config) (*grpc.ClientConn, error) {
	opts := []grpc.DialOption{
		grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			Time:                30 * time.Second,
			Timeout:             10 * time.Second,
			PermitWithoutStream: true,
		}),
	}

	if cfg.TLSConfig != nil {
		opts = append(opts, grpc.WithTransportCredentials(credentials.NewTLS(cfg.TLSConfig)))
	} else {
		opts = append(opts, grpc.WithTransportCredentials(insecure.NewCredentials()))
	}

	return grpc.NewClient(cfg.Target, opts...)
}
