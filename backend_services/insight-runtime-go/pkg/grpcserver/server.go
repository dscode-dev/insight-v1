// Package grpcserver builds gRPC servers with the standard Insight
// interceptor stack:
//
//   - panic recovery
//   - OpenTelemetry tracing
//   - structured logging
//   - (optional) mTLS via TLS server config
//
// Callers register their gRPC services and call Serve(net.Listener).
package grpcserver

import (
	"context"
	"crypto/tls"
	"errors"
	"net"

	"github.com/rs/zerolog"
	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
)

type Config struct {
	// Set TLSConfig to enforce mTLS. Leave nil for plaintext
	// (acceptable in lab; production must always set this).
	TLSConfig *tls.Config
}

// New returns a *grpc.Server with the standard interceptors. Callers
// register services on the returned server then call Serve(net.Listener).
func New(cfg Config) *grpc.Server {
	opts := []grpc.ServerOption{
		grpc.UnaryInterceptor(chainUnary(
			recoveryInterceptor(),
			loggingInterceptor(),
		)),
		grpc.StreamInterceptor(recoveryStreamInterceptor()),
		grpc.StatsHandler(otelgrpc.NewServerHandler()),
	}

	if cfg.TLSConfig != nil {
		opts = append(opts, grpc.Creds(credentials.NewTLS(cfg.TLSConfig)))
	} else {
		opts = append(opts, grpc.Creds(insecure.NewCredentials()))
	}

	return grpc.NewServer(opts...)
}

// Listen wraps net.Listen with a small helper that fails fast if the
// address is already in use — useful in tests + lab deploys where
// "address already in use" is the #1 boot error.
func Listen(addr string) (net.Listener, error) {
	lis, err := net.Listen("tcp", addr)
	if err != nil {
		var opErr *net.OpError
		if errors.As(err, &opErr) {
			return nil, opErr
		}
		return nil, err
	}
	return lis, nil
}

// ---- interceptors ----

func chainUnary(interceptors ...grpc.UnaryServerInterceptor) grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		chain := handler
		for i := len(interceptors) - 1; i >= 0; i-- {
			interceptor := interceptors[i]
			inner := chain
			chain = func(ctx context.Context, req any) (any, error) {
				return interceptor(ctx, req, info, inner)
			}
		}
		return chain(ctx, req)
	}
}

func recoveryInterceptor() grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (resp any, err error) {
		defer func() {
			if rec := recover(); rec != nil {
				zerolog.Ctx(ctx).Error().
					Interface("panic", rec).
					Str("method", info.FullMethod).
					Msg("grpc_panic")
				err = status.Errorf(codes.Internal, "internal error")
			}
		}()
		return handler(ctx, req)
	}
}

func recoveryStreamInterceptor() grpc.StreamServerInterceptor {
	return func(srv any, ss grpc.ServerStream, info *grpc.StreamServerInfo, handler grpc.StreamHandler) (err error) {
		defer func() {
			if rec := recover(); rec != nil {
				zerolog.Ctx(ss.Context()).Error().
					Interface("panic", rec).
					Str("method", info.FullMethod).
					Msg("grpc_stream_panic")
				err = status.Errorf(codes.Internal, "internal error")
			}
		}()
		return handler(srv, ss)
	}
}

func loggingInterceptor() grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		resp, err := handler(ctx, req)
		evt := zerolog.Ctx(ctx).Info()
		if err != nil {
			st, _ := status.FromError(err)
			evt = zerolog.Ctx(ctx).Warn().
				Str("grpc_code", st.Code().String()).
				Str("grpc_message", st.Message())
		}
		evt.Str("method", info.FullMethod).Msg("grpc_handled")
		return resp, err
	}
}
