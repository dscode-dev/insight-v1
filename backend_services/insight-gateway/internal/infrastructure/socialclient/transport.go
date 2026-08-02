// Transport-level concerns for the social client — Sprint 2.5 Part 2.
//
// retryReadsInterceptor: bounded retry of IDEMPOTENT reads on
// transient upstream unavailability. Reads are identified by method
// name prefix (Get/List/Global/Following) — mutations always fail
// fast so the caller controls retry semantics end-to-end.
//
// propagationInterceptor: forwards the authenticated user id and the
// request id as outgoing gRPC metadata so Social-side logs/traces
// correlate with the Gateway request. Social treats these as
// OBSERVABILITY hints only — authorization inputs always travel in
// the request messages themselves.
package socialclient

import (
	"context"
	"strings"
	"time"

	"github.com/google/uuid"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type ctxKey int

const (
	userIDKey ctxKey = iota
	requestIDKey
)

// WithUserID annotates the outgoing context with the authenticated
// user id for cross-service correlation.
func WithUserID(ctx context.Context, id uuid.UUID) context.Context {
	return context.WithValue(ctx, userIDKey, id.String())
}

// WithRequestID annotates the outgoing context with the gateway
// request id (tracing propagation).
func WithRequestID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, requestIDKey, id)
}

func propagationInterceptor() grpc.UnaryClientInterceptor {
	return func(
		ctx context.Context,
		method string,
		req, reply any,
		cc *grpc.ClientConn,
		invoker grpc.UnaryInvoker,
		opts ...grpc.CallOption,
	) error {
		var pairs []string
		if v, ok := ctx.Value(userIDKey).(string); ok && v != "" {
			pairs = append(pairs, "x-insight-user-id", v)
		}
		if v, ok := ctx.Value(requestIDKey).(string); ok && v != "" {
			pairs = append(pairs, "x-request-id", v)
		}
		if len(pairs) > 0 {
			ctx = metadata.AppendToOutgoingContext(ctx, pairs...)
		}
		return invoker(ctx, method, req, reply, cc, opts...)
	}
}

// readMethod reports whether a full gRPC method name is an idempotent
// read by Social's naming convention.
func readMethod(fullMethod string) bool {
	idx := strings.LastIndex(fullMethod, "/")
	if idx < 0 {
		return false
	}
	name := fullMethod[idx+1:]
	for _, prefix := range []string{"Get", "List", "Global", "Following", "Stats"} {
		if strings.HasPrefix(name, prefix) {
			return true
		}
	}
	return false
}

func retryReadsInterceptor(maxRetries int) grpc.UnaryClientInterceptor {
	return func(
		ctx context.Context,
		method string,
		req, reply any,
		cc *grpc.ClientConn,
		invoker grpc.UnaryInvoker,
		opts ...grpc.CallOption,
	) error {
		err := invoker(ctx, method, req, reply, cc, opts...)
		if err == nil || !readMethod(method) {
			return err
		}
		for attempt := 1; attempt <= maxRetries; attempt++ {
			if status.Code(err) != codes.Unavailable {
				return err
			}
			select {
			case <-ctx.Done():
				return err
			case <-time.After(time.Duration(100*(1<<(attempt-1))) * time.Millisecond):
			}
			err = invoker(ctx, method, req, reply, cc, opts...)
			if err == nil {
				return nil
			}
		}
		return err
	}
}
