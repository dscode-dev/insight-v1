// Redis Streams Publisher — Sprint 5 V1 integration.
//
// Replaces the Sprint 1 noop with the real downstream transport
// the rest of the platform consumes. Atlas (Python) reads from
// `insight:stream:events:match` and `insight:stream:events:context`;
// future Anvil (analytics) reads from `insight:stream:events:odds`.
//
// Wire envelope (JSON):
//
//	{
//	  "schema_version": "v1",
//	  "stream": "match" | "odds" | "context",
//	  "idempotency_key": "<canonical_event_id>::<status>",
//	  "event": {
//	    "event_id": "<uuid>",
//	    "schema_version": "v1",
//	    "event_type": "match.result",
//	    "occurred_at": "<RFC3339 UTC>",
//	    "competition_id": "<uuid>",
//	    "match_id": "<uuid>",
//	    "payload": {...},
//	    "source": {...primary SourceRef...},
//	    "lineage": [...all SourceRefs...]
//	  },
//	  "published_at": "<RFC3339 UTC>"
//	}
//
// Idempotency: Redis Streams entries do NOT dedup at write time, so
// downstream consumers MUST honour idempotency_key when persisting.
// We additionally XADD with MAXLEN ~ MaxLen so an unbounded
// producer cannot blow the cluster up.
//
// Architectural rule: this package is the ONLY place CanonicalSportsEvent
// is serialised for the wire. Adding new fields requires a new
// schema_version + a backwards-compat path here.
package publishing

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// SchemaVersion — bumped only when the on-wire shape changes in a
// non-additive way. Atlas + downstream consumers read this and may
// refuse unknown values.
const SchemaVersion = "v1"

// RedisConfig — wire shape from the composition root.
type RedisConfig struct {
	Addr        string
	Password    string
	DB          int
	StreamMatch string // default "insight:stream:events:match"
	StreamOdds  string // default "insight:stream:events:odds"
	StreamCtx   string // default "insight:stream:events:context"
	MaxLen      int64  // XADD MAXLEN ~ N. 0 disables trimming.
	DialTimeout time.Duration
}

// Defaults applies safe defaults. Returns the config for chaining.
func (c RedisConfig) Defaults() RedisConfig {
	if c.StreamMatch == "" {
		c.StreamMatch = "insight:stream:events:match"
	}
	if c.StreamOdds == "" {
		c.StreamOdds = "insight:stream:events:odds"
	}
	if c.StreamCtx == "" {
		c.StreamCtx = "insight:stream:events:context"
	}
	if c.MaxLen <= 0 {
		c.MaxLen = 100_000
	}
	if c.DialTimeout <= 0 {
		c.DialTimeout = 5 * time.Second
	}
	return c
}

// RedisPublisher satisfies ports.Publisher using Redis Streams.
type RedisPublisher struct {
	client *goredis.Client
	cfg    RedisConfig
	logger zerolog.Logger
}

// NewRedis pings Redis at construction so the boot path fails loudly
// when the cluster is unreachable.
func NewRedis(ctx context.Context, cfg RedisConfig, logger zerolog.Logger) (*RedisPublisher, error) {
	cfg = cfg.Defaults()
	client := goredis.NewClient(&goredis.Options{
		Addr:        cfg.Addr,
		Password:    cfg.Password,
		DB:          cfg.DB,
		DialTimeout: cfg.DialTimeout,
	})
	if err := client.Ping(ctx).Err(); err != nil {
		_ = client.Close()
		return nil, fmt.Errorf("publish: redis ping: %w", err)
	}
	logger.Info().
		Str("addr", cfg.Addr).
		Str("stream_match", cfg.StreamMatch).
		Str("stream_context", cfg.StreamCtx).
		Msg("publish_redis_connected")
	return &RedisPublisher{client: client, cfg: cfg, logger: logger}, nil
}

func (p *RedisPublisher) streamFor(s ports.Stream) string {
	switch s {
	case ports.StreamMatch:
		return p.cfg.StreamMatch
	case ports.StreamOdds:
		return p.cfg.StreamOdds
	default:
		return p.cfg.StreamCtx
	}
}

// wireEnvelope is the JSON shape every downstream consumer sees.
// Renaming a JSON tag is a schema break — bump SchemaVersion.
type wireEnvelope struct {
	SchemaVersion  string          `json:"schema_version"`
	Stream         string          `json:"stream"`
	IdempotencyKey string          `json:"idempotency_key"`
	Event          json.RawMessage `json:"event"`
	PublishedAt    string          `json:"published_at"`
}

type canonicalWireEvent struct {
	EventID       string             `json:"event_id"`
	SchemaVersion string             `json:"schema_version"`
	EventType     string             `json:"event_type"`
	OccurredAt    string             `json:"occurred_at"`
	CompetitionID string             `json:"competition_id"`
	MatchID       string             `json:"match_id,omitempty"`
	Payload       map[string]any     `json:"payload"`
	Source        source.SourceRef   `json:"source"`
	Lineage       []source.SourceRef `json:"lineage"`
	Status        string             `json:"status"`
	Sport         string             `json:"sport"`
	Season        string             `json:"season,omitempty"`
	Confidence    float64            `json:"confidence"`
}

// Publish — XADD a JSON-encoded envelope to the routed stream.
// Caller is the application-level PublishingService which already
// decided which Stream applies.
func (p *RedisPublisher) Publish(ctx context.Context, env ports.PublishEnvelope) error {
	lineage := env.Event.Sources()
	if len(lineage) == 0 {
		return fmt.Errorf("publish: canonical event has no lineage")
	}
	wireEvent := canonicalWireEvent{
		EventID:       env.Event.EventID().String(),
		SchemaVersion: SchemaVersion,
		EventType:     env.Event.EventType(),
		OccurredAt:    env.Event.OccurredAt().UTC().Format(time.RFC3339Nano),
		CompetitionID: env.Event.CompetitionID().String(),
		MatchID:       env.Event.MatchID().String(),
		Payload:       env.Event.Payload(),
		Source:        lineage[0],
		Lineage:       lineage,
		Status:        string(env.Event.Status()),
		Sport:         string(env.Event.Sport()),
		Season:        env.Event.Season(),
		Confidence:    env.Event.Confidence(),
	}
	eventJSON, err := json.Marshal(wireEvent)
	if err != nil {
		return fmt.Errorf("publish: marshal event: %w", err)
	}
	body, err := json.Marshal(wireEnvelope{
		SchemaVersion:  SchemaVersion,
		Stream:         string(env.Stream),
		IdempotencyKey: env.IdempotencyKey,
		Event:          eventJSON,
		PublishedAt:    time.Now().UTC().Format(time.RFC3339Nano),
	})
	if err != nil {
		return fmt.Errorf("publish: marshal envelope: %w", err)
	}
	stream := p.streamFor(env.Stream)
	id, err := p.client.XAdd(ctx, &goredis.XAddArgs{
		Stream: stream,
		MaxLen: p.cfg.MaxLen,
		Approx: true,
		Values: map[string]any{
			"schema_version":  SchemaVersion,
			"idempotency_key": env.IdempotencyKey,
			"payload":         body,
		},
	}).Result()
	if err != nil {
		p.logger.Warn().Err(err).
			Str("stream", stream).
			Str("idempotency_key", env.IdempotencyKey).
			Msg("publish_failed")
		return fmt.Errorf("publish: XADD: %w", err)
	}
	p.logger.Info().
		Str("stream", stream).
		Str("entry_id", id).
		Str("idempotency_key", env.IdempotencyKey).
		Str("canonical_event_id", env.Event.EventID().String()).
		Str("status", string(env.Event.Status())).
		Int("source_count", env.Event.SourceCount()).
		Msg("canonical_published")
	return nil
}

// Close releases the Redis client. Idempotent at the underlying
// client (closing twice returns the second error from go-redis but
// no panic).
func (p *RedisPublisher) Close() error { return p.client.Close() }
