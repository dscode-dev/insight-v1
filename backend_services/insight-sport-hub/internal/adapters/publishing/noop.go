// Package publishing — no-op Publisher implementation.
//
// Sprint 1 fulfils the architectural rule "define publishing
// contracts only" — events are routed by the application layer
// through the typed envelope but the underlying transport (Redis
// Streams) is NOT wired. This adapter discards every call after
// logging it at debug level so dry-run integration tests can
// confirm the path works end-to-end.
//
// Sprint 2 replaces this with a Redis Streams adapter that
// preserves the full envelope (including the SourceRef slice
// inside the CanonicalSportsEvent payload).
package publishing

import (
	"context"

	"github.com/rs/zerolog/log"

	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

type Noop struct{}

func NewNoop() *Noop { return &Noop{} }

func (Noop) Publish(ctx context.Context, env ports.PublishEnvelope) error {
	log.Ctx(ctx).Debug().
		Str("stream", string(env.Stream)).
		Str("idempotency_key", env.IdempotencyKey).
		Str("canonical_event_id", env.Event.EventID().String()).
		Str("status", string(env.Event.Status())).
		Int("source_count", env.Event.SourceCount()).
		Msg("publish_noop")
	return nil
}
