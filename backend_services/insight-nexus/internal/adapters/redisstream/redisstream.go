// Package redisstream — Nexus's two Redis touchpoints:
//
//   - Consumer: XREADGROUP off insight:stream:trends (the ONLY input
//     Nexus has — never raw events, never Sport Hub streams, never
//     Atlas databases).
//   - Queue: XADD onto the per-agent publishing queues
//     (insight:queue:nexus:{agent}). Atlas never knows these exist.
//
// This package is the only Nexus code importing go-redis (enforced by
// the boundary test).
package redisstream

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// ---- trend consumer ---------------------------------------------------------

// Handler is the application seam the consumer dispatches into.
type Handler func(ctx context.Context, env trend.Envelope) error

type ConsumerConfig struct {
	Addr     string
	Password string
	DB       int
	Stream   string // default insight:stream:trends
	Group    string // default insight-nexus
	Consumer string // instance name
	BlockMS  int
	Batch    int64
	// Claimer — Sprint 3.5 pending recovery + DLQ.
	Claimer ClaimerConfig
}

func (c ConsumerConfig) defaults() ConsumerConfig {
	if c.Stream == "" {
		c.Stream = "insight:stream:trends"
	}
	if c.Group == "" {
		c.Group = "insight-nexus"
	}
	if c.Consumer == "" {
		c.Consumer = "nexus-1"
	}
	if c.BlockMS <= 0 {
		c.BlockMS = 5000
	}
	if c.Batch <= 0 {
		c.Batch = 32
	}
	c.Claimer = c.Claimer.defaults()
	return c
}

type Consumer struct {
	client    *goredis.Client
	cfg       ConsumerConfig
	logger    zerolog.Logger
	lastClaim time.Time
}

// NewConsumer connects + ensures the consumer group exists.
func NewConsumer(ctx context.Context, cfg ConsumerConfig, logger zerolog.Logger) (*Consumer, error) {
	cfg = cfg.defaults()
	client := goredis.NewClient(&goredis.Options{
		Addr: cfg.Addr, Password: cfg.Password, DB: cfg.DB,
	})
	if err := client.Ping(ctx).Err(); err != nil {
		_ = client.Close()
		return nil, fmt.Errorf("redisstream: ping: %w", err)
	}
	err := client.XGroupCreateMkStream(ctx, cfg.Stream, cfg.Group, "$").Err()
	if err != nil && !isBusyGroup(err) {
		_ = client.Close()
		return nil, fmt.Errorf("redisstream: group create: %w", err)
	}
	logger.Info().
		Str("stream", cfg.Stream).
		Str("group", cfg.Group).
		Msg("nexus_trend_consumer_connected")
	return &Consumer{client: client, cfg: cfg, logger: logger}, nil
}

// Run blocks consuming until ctx cancels. Decode failures (poison) are
// dead-lettered to the DLQ stream and only then ACKed — never silently
// discarded; if the DLQ write fails the entry stays pending (better
// stuck than lost). Handler failures stay pending for redelivery.
func (c *Consumer) Run(ctx context.Context, handler Handler) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		// Sprint 3.5 — pending recovery pass on a time gate.
		if c.cfg.Claimer.Enabled && time.Since(c.lastClaim) >= c.cfg.Claimer.Interval {
			c.reclaimPending(ctx, handler)
			c.lastClaim = time.Now()
		}
		streams, err := c.client.XReadGroup(ctx, &goredis.XReadGroupArgs{
			Group:    c.cfg.Group,
			Consumer: c.cfg.Consumer,
			Streams:  []string{c.cfg.Stream, ">"},
			Count:    c.cfg.Batch,
			Block:    time.Duration(c.cfg.BlockMS) * time.Millisecond,
		}).Result()
		if err != nil {
			if err == goredis.Nil || ctx.Err() != nil {
				continue
			}
			c.logger.Warn().Err(err).Msg("nexus_consumer_read_error")
			time.Sleep(time.Second)
			continue
		}
		for _, stream := range streams {
			for _, msg := range stream.Messages {
				c.dispatch(ctx, msg, handler)
			}
		}
	}
}

func (c *Consumer) dispatch(ctx context.Context, msg goredis.XMessage, handler Handler) {
	payload, _ := msg.Values["payload"].(string)
	env, err := trend.DecodeEnvelope([]byte(payload))
	if err != nil {
		c.poison(ctx, msg, payload, err)
		return
	}
	if err := handler(ctx, env); err != nil {
		c.logger.Error().Err(err).
			Str("entry_id", msg.ID).
			Str("trend_id", env.Trend.TrendID).
			Msg("nexus_trend_handler_failed")
		// No ack — stays pending for redelivery/reclaim.
		return
	}
	_ = c.client.XAck(ctx, c.cfg.Stream, c.cfg.Group, msg.ID).Err()
}

func (c *Consumer) Close() error { return c.client.Close() }

func isBusyGroup(err error) bool {
	return err != nil && len(err.Error()) >= 9 && err.Error()[:9] == "BUSYGROUP"
}

// ---- per-agent publishing queues ---------------------------------------------

type Queue struct {
	client   *goredis.Client
	maxLen   int64
	group    string
	consumer string
	logger   zerolog.Logger
}

// QueueConfig — the publishing queues' connection and consumer identity.
type QueueConfig struct {
	Addr     string
	Password string
	DB       int
	MaxLen   int64
	// Group / Consumer name the read side. They are separate from the
	// trend consumer's group: the two streams have different retry
	// characteristics, and sharing a group name would make a reset of one
	// silently reset the other.
	Group    string
	Consumer string
}

// NewQueue reuses the caller's client config; queues are plain streams.
func NewQueue(ctx context.Context, cfg QueueConfig, logger zerolog.Logger) (*Queue, error) {
	client := goredis.NewClient(&goredis.Options{
		Addr: cfg.Addr, Password: cfg.Password, DB: cfg.DB,
	})
	if err := client.Ping(ctx).Err(); err != nil {
		_ = client.Close()
		return nil, fmt.Errorf("redisstream: queue ping: %w", err)
	}
	if cfg.MaxLen <= 0 {
		cfg.MaxLen = 50_000
	}
	if cfg.Group == "" {
		cfg.Group = "insight-nexus-publish"
	}
	if cfg.Consumer == "" {
		cfg.Consumer = "publisher-1"
	}
	return &Queue{
		client:   client,
		maxLen:   cfg.MaxLen,
		group:    cfg.Group,
		consumer: cfg.Consumer,
		logger:   logger,
	}, nil
}

func (q *Queue) Enqueue(ctx context.Context, queueName string, item ports.QueuedDraft) error {
	body, err := json.Marshal(item)
	if err != nil {
		return fmt.Errorf("redisstream: marshal queued draft: %w", err)
	}
	// MaxLen is NOT applied here.
	//
	// It used to be, with Approx, which trims the OLDEST entries — and the
	// oldest entry on a publishing queue is a draft that has waited longest
	// to be published. Capping the queue therefore discarded exactly the
	// work that was most overdue, silently. A backlog is a problem to
	// alarm on (queueDepth), not one to hide by deleting its head.
	//
	// The bound that does exist is the consumer group: unacked entries are
	// redelivered, and the DLQ absorbs what repeatedly fails.
	return q.client.XAdd(ctx, &goredis.XAddArgs{
		Stream: queueName,
		Values: map[string]any{
			"draft_id": item.Draft.ID.String(),
			"agent_id": item.Draft.AgentID.String(),
			"priority": fmt.Sprintf("%t", item.Priority),
			"queued_at": time.Now().UTC().
				Format(time.RFC3339),
			"payload": body,
		},
	}).Err()
}

func (q *Queue) Depth(ctx context.Context, queueName string) (int64, error) {
	return q.client.XLen(ctx, queueName).Result()
}

// MaxLen reports the configured cap, which is now advisory: it bounds
// nothing, and exists so the depth gauge can be compared against the value
// the operator believed was in force.
func (q *Queue) MaxLen() int64 { return q.maxLen }

func (q *Queue) Close() error { return q.client.Close() }

// ---- publishing queue consumer ------------------------------------------

// Consume drains every per-agent queue through one consumer group each.
//
// One goroutine per queue, so a slow agent (an LLM that always times out for
// its persona) delays only its own backlog. Sharing a goroutine would let
// that one agent block every other agent's posts — the failure mode the
// inline publisher had, just moved.
func (q *Queue) Consume(
	ctx context.Context, queueNames []string, handler ports.QueuedDraftHandler,
) error {
	if len(queueNames) == 0 {
		<-ctx.Done()
		return ctx.Err()
	}
	var wg sync.WaitGroup
	for _, name := range queueNames {
		if err := q.ensureGroup(ctx, name); err != nil {
			return err
		}
		wg.Add(1)
		go func(queueName string) {
			defer wg.Done()
			q.consumeOne(ctx, queueName, handler)
		}(name)
	}
	wg.Wait()
	return ctx.Err()
}

func (q *Queue) ensureGroup(ctx context.Context, queueName string) error {
	// "0" and not "$": a group created at "$" skips everything already
	// waiting, so enabling the worker would abandon the existing backlog.
	err := q.client.XGroupCreateMkStream(ctx, queueName, q.group, "0").Err()
	if err != nil && !isBusyGroup(err) {
		return fmt.Errorf("redisstream: queue group %s: %w", queueName, err)
	}
	return nil
}

func (q *Queue) consumeOne(
	ctx context.Context, queueName string, handler ports.QueuedDraftHandler,
) {
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		streams, err := q.client.XReadGroup(ctx, &goredis.XReadGroupArgs{
			Group:    q.group,
			Consumer: q.consumer,
			Streams:  []string{queueName, ">"},
			Count:    1, // one draft at a time: each is an LLM call.
			Block:    5 * time.Second,
		}).Result()
		if err != nil {
			if err == goredis.Nil || ctx.Err() != nil {
				continue
			}
			q.logger.Warn().Err(err).
				Str("queue", queueName).
				Msg("nexus_publish_queue_read_error")
			time.Sleep(time.Second)
			continue
		}
		for _, stream := range streams {
			for _, msg := range stream.Messages {
				q.dispatchQueued(ctx, queueName, msg, handler)
			}
		}
	}
}

func (q *Queue) dispatchQueued(
	ctx context.Context, queueName string, msg goredis.XMessage,
	handler ports.QueuedDraftHandler,
) {
	payload, _ := msg.Values["payload"].(string)
	var item ports.QueuedDraft
	if err := json.Unmarshal([]byte(payload), &item); err != nil {
		// Undecodable: it can never succeed on redelivery, so ACK it
		// rather than let it block the queue head forever. It is logged
		// with the entry id so the payload stays recoverable from the
		// stream until trimmed.
		q.logger.Error().Err(err).
			Str("queue", queueName).
			Str("entry_id", msg.ID).
			Msg("nexus_publish_queue_undecodable_entry")
		_ = q.client.XAck(ctx, queueName, q.group, msg.ID).Err()
		return
	}
	if err := handler(ctx, item); err != nil {
		q.logger.Error().Err(err).
			Str("queue", queueName).
			Str("entry_id", msg.ID).
			Str("draft_id", item.Draft.ID.String()).
			Msg("nexus_publish_failed_entry_stays_pending")
		return // no ACK — redelivered.
	}
	_ = q.client.XAck(ctx, queueName, q.group, msg.ID).Err()
}
