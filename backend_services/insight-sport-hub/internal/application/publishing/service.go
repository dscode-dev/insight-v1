// Package publishing — PublishingService.
//
// Sprint 1: contracts only. The service exposes a typed Publish
// method that routes a CanonicalSportsEvent to the right Stream
// and wraps the call with idempotency + observability. The
// underlying Publisher port is a no-op in Sprint 1; Sprint 2 wires
// the Redis Streams adapter.
//
// Routing rules (Sprint 1):
//
//	event_type starting with "match." → StreamMatch
//	event_type starting with "odds."  → StreamOdds
//	anything else                     → StreamContext
//
// Routing is intentionally string-based + simple — a future map-driven
// router can replace this once the event_type taxonomy stabilises.
package publishing

import (
	"context"
	"strings"

	"github.com/rs/zerolog/log"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// PublishGate is an optional pre-publish filter. Sprint 6.1 wires the
// odds change-detection gate here so sub-threshold odds ticks are
// suppressed from the stream (denoising) while the Hub still persists
// them upstream (audit). A nil gate publishes everything.
type PublishGate interface {
	ShouldPublish(ctx context.Context, c *event.CanonicalSportsEvent) (bool, error)
}

type Service struct {
	pub  ports.Publisher
	gate PublishGate
}

// Option configures the Service. Kept variadic so the Sprint-1
// New(pub) call sites stay source-compatible.
type Option func(*Service)

// WithGate installs a pre-publish filter (Sprint 6.1).
func WithGate(g PublishGate) Option {
	return func(s *Service) { s.gate = g }
}

func New(pub ports.Publisher, opts ...Option) *Service {
	s := &Service{pub: pub}
	for _, o := range opts {
		o(s)
	}
	return s
}

// Publish wraps the publisher with stream routing + idempotency
// key derivation. The key combines the canonical event_id + a tag
// for the status — different statuses are different "facts" worth
// emitting (a candidate that flips to conflicting is a NEW event
// for downstream).
//
// When a gate is installed it runs first: a "skip" verdict short-
// circuits to a successful no-op (the event was already persisted
// upstream; suppressing the publish is intentional denoising, not an
// error). A gate ERROR fails open — the event publishes — because
// dropping a meaningful odds move is worse than an extra stream entry.
func (s *Service) Publish(ctx context.Context, c *event.CanonicalSportsEvent) error {
	if s.gate != nil {
		ok, err := s.gate.ShouldPublish(ctx, c)
		if err != nil {
			log.Ctx(ctx).Warn().Err(err).
				Str("event_type", c.EventType()).
				Str("canonical_event_id", c.EventID().String()).
				Msg("publish_gate_error_fail_open")
		} else if !ok {
			log.Ctx(ctx).Debug().
				Str("canonical_event_id", c.EventID().String()).
				Msg("odds_publish_suppressed_below_threshold")
			return nil
		}
	}
	env := ports.PublishEnvelope{
		Stream:         routeFor(c.EventType()),
		IdempotencyKey: c.EventID().String() + "::" + string(c.Status()),
		Event:          c,
	}
	return s.pub.Publish(ctx, env)
}

func routeFor(eventType string) ports.Stream {
	switch {
	// Odds are their own event category. "match.odds" shares the
	// "match." prefix but belongs on the odds stream, so it MUST be
	// matched before the generic match rule below.
	case eventType == "match.odds" || strings.HasPrefix(eventType, "odds."):
		return ports.StreamOdds
	case strings.HasPrefix(eventType, "match."):
		return ports.StreamMatch
	default:
		return ports.StreamContext
	}
}
