// Package socialclient is the gRPC client wrapper for talking to
// insight-social.
//
// Holds one ClientConn dialed at boot, plus typed handles to each of
// the 7 social.v1 service stubs. The BFF handlers consume those typed
// handles; nothing in interfaces/http/social/ ever sees the raw
// ClientConn.
//
// Connection posture:
//   - mTLS via cert-manager-mounted bundle when TLSCertPath/KeyPath/
//     CAPath are all set; plaintext fallback in lab.
//   - Round-robin load balancing across all backend pods via the
//     headless DNS service (`dns:///insight-social-headless.insight.svc.cluster.local:50051`).
//     `dns:///` triggers grpc-go's DNS resolver + round_robin LB
//     policy — without this scheme prefix you get pin-to-first-IP.
//   - Keepalive: ping every 30s, kill the conn if no ack in 10s.
//     Keeps long-idle conns from hanging on dropped NAT mappings.
package socialclient

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"os"
	"time"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/connectivity"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/keepalive"
)

// Config captures the dial knobs. Sourced from gateway Settings in main.go.
type Config struct {
	// Target is the gRPC target string. In prod, prefix with `dns:///`
	// so grpc-go uses the DNS resolver — required for round-robin
	// load balancing over a headless Service.
	Target string

	// TLS — mTLS when all three are set; insecure otherwise.
	TLSCertPath string
	TLSKeyPath  string
	TLSCAPath   string

	// ServerName overrides the SNI / cert verification hostname. Set
	// when Target is an IP or non-matching DNS name. Empty = derive
	// from Target.
	ServerName string

	// DialTimeout bounds the initial connection — grpc.Dial is now
	// non-blocking by default (since v1.62), so this only affects
	// the explicit `WaitForReady` call we make at boot.
	DialTimeout time.Duration
}

// Client bundles every social.v1 service stub.
type Client struct {
	conn *grpc.ClientConn

	User         socialv1.UserServiceClient
	Community    socialv1.CommunityServiceClient
	Discussion   socialv1.DiscussionServiceClient
	Signal       socialv1.SignalServiceClient
	Sentiment    socialv1.SentimentServiceClient
	Relationship socialv1.RelationshipServiceClient
	Reputation   socialv1.ReputationServiceClient
	Reaction     socialv1.ReactionServiceClient // Sprint B
	// Sprint 2.5 — Social Foundation surfaces (Gateway Social BFF).
	Agent socialv1.AgentServiceClient
	Post  socialv1.PostServiceClient
	Feed  socialv1.FeedServiceClient
	// FEATURE-NOTIFICATIONS-V1 — notification read/mark surface.
	Notification socialv1.NotificationServiceClient
}

// State reports the underlying gRPC connection state (CONSOLE-OPS-A2 platform
// health). Ready/Idle = reachable; Connecting = warming; TransientFailure/
// Shutdown = unreachable. Lets the console platform-health endpoint report a
// real social status without issuing a full RPC.
func (c *Client) State() connectivity.State {
	if c == nil || c.conn == nil {
		return connectivity.Shutdown
	}
	return c.conn.GetState()
}

// New dials the social service and returns the bundled client. The
// caller MUST call Close() on graceful shutdown.
func New(ctx context.Context, cfg Config) (*Client, error) {
	if cfg.Target == "" {
		return nil, errors.New("socialclient: Target required")
	}
	if cfg.DialTimeout == 0 {
		cfg.DialTimeout = 5 * time.Second
	}

	creds, err := buildCreds(cfg)
	if err != nil {
		return nil, fmt.Errorf("socialclient: build creds: %w", err)
	}

	// Service config selects round_robin across resolved addresses
	// instead of the default `pick_first` (which sticks to one pod).
	const svcCfg = `{"loadBalancingPolicy":"round_robin"}`

	opts := []grpc.DialOption{
		grpc.WithTransportCredentials(creds),
		grpc.WithDefaultServiceConfig(svcCfg),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			Time:                30 * time.Second,
			Timeout:             10 * time.Second,
			PermitWithoutStream: true,
		}),
		// Generous default — bigger than the typical social response
		// (Discussion list, paged) without being so big a runaway
		// upstream could OOM us.
		grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(8 << 20)),
		// Sprint 2.5 — transport-level retry for IDEMPOTENT reads on
		// transient upstream unavailability + auth/trace metadata
		// propagation. Mutations are never retried here; the handler
		// (and ultimately the mobile client) owns those semantics.
		grpc.WithChainUnaryInterceptor(
			retryReadsInterceptor(2),
			propagationInterceptor(),
		),
	}

	//nolint:staticcheck // grpc.NewClient is the v1.62+ replacement; we
	// use Dial here because it's still the supported entry point for
	// the v1.67 line we pin.
	conn, err := grpc.DialContext(ctx, cfg.Target, opts...)
	if err != nil {
		return nil, fmt.Errorf("socialclient: dial %s: %w", cfg.Target, err)
	}

	return &Client{
		conn:         conn,
		User:         socialv1.NewUserServiceClient(conn),
		Community:    socialv1.NewCommunityServiceClient(conn),
		Discussion:   socialv1.NewDiscussionServiceClient(conn),
		Signal:       socialv1.NewSignalServiceClient(conn),
		Sentiment:    socialv1.NewSentimentServiceClient(conn),
		Relationship: socialv1.NewRelationshipServiceClient(conn),
		Reputation:   socialv1.NewReputationServiceClient(conn),
		Reaction:     socialv1.NewReactionServiceClient(conn),
		Agent:        socialv1.NewAgentServiceClient(conn),
		Post:         socialv1.NewPostServiceClient(conn),
		Feed:         socialv1.NewFeedServiceClient(conn),
		Notification: socialv1.NewNotificationServiceClient(conn),
	}, nil
}

// Close releases the underlying gRPC connection.
func (c *Client) Close() error {
	if c == nil || c.conn == nil {
		return nil
	}
	return c.conn.Close()
}

// buildCreds picks mTLS when all three TLS paths are set; otherwise
// returns insecure creds. Mirrors the server-side mTLS decision in
// insight-social/cmd/social/main.go — same lab/prod symmetry.
func buildCreds(cfg Config) (credentials.TransportCredentials, error) {
	if cfg.TLSCertPath == "" || cfg.TLSKeyPath == "" || cfg.TLSCAPath == "" {
		return insecure.NewCredentials(), nil
	}
	cert, err := tls.LoadX509KeyPair(cfg.TLSCertPath, cfg.TLSKeyPath)
	if err != nil {
		return nil, fmt.Errorf("load client keypair: %w", err)
	}
	caBytes, err := os.ReadFile(cfg.TLSCAPath)
	if err != nil {
		return nil, fmt.Errorf("read ca: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caBytes) {
		return nil, errors.New("ca bundle empty or malformed")
	}
	tlsCfg := &tls.Config{
		Certificates: []tls.Certificate{cert},
		RootCAs:      pool,
		MinVersion:   tls.VersionTLS13,
	}
	if cfg.ServerName != "" {
		tlsCfg.ServerName = cfg.ServerName
	}
	return credentials.NewTLS(tlsCfg), nil
}
