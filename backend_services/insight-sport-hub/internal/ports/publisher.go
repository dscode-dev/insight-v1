package ports

import (
	"context"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
)

// Stream identifies which downstream consumer group a published
// envelope is destined for. Mirrors the planned Redis Stream keys:
//
//	insight:stream:events:match    — match-lifecycle events
//	insight:stream:events:odds     — market movement / odds events
//	insight:stream:events:context  — anything else the platform needs
//
// String slugs are the wire contract — additive-only, never rename.
type Stream string

const (
	StreamMatch   Stream = "match"
	StreamOdds    Stream = "odds"
	StreamContext Stream = "context"
)

// PublishEnvelope is the bundle the application layer hands to the
// publisher. We don't reuse CanonicalSportsEvent directly because
// publishing may want to project a subset (e.g. omit large payload
// fields, attach a target Stream, attach an idempotency key for
// consumer-side dedup).
//
// Sprint 1: contracts only. The noop publisher discards.
// Sprint 2+: Redis Streams adapter implements Publish.
type PublishEnvelope struct {
	Stream         Stream
	IdempotencyKey string
	Event          *event.CanonicalSportsEvent
}

// Publisher is the only thing the application layer knows about the
// outbound side. Implementations:
//
//	Sprint 1  — noop (discards + logs)
//	Sprint 2+ — Redis Streams (preserves full SourceRef + payload)
type Publisher interface {
	// Publish must be idempotent on IdempotencyKey. Returns an error
	// only on infrastructure failure — successful no-op (e.g. dup
	// key already consumed) returns nil.
	Publish(ctx context.Context, env PublishEnvelope) error
}
