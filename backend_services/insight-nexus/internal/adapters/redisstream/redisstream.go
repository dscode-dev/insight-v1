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
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
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
	client *goredis.Client
	maxLen int64
}

// NewQueue reuses the caller's client config; queues are plain streams.
func NewQueue(ctx context.Context, addr, password string, db int, maxLen int64) (*Queue, error) {
	client := goredis.NewClient(&goredis.Options{Addr: addr, Password: password, DB: db})
	if err := client.Ping(ctx).Err(); err != nil {
		_ = client.Close()
		return nil, fmt.Errorf("redisstream: queue ping: %w", err)
	}
	if maxLen <= 0 {
		maxLen = 50_000
	}
	return &Queue{client: client, maxLen: maxLen}, nil
}

func (q *Queue) Enqueue(ctx context.Context, queueName string, d draft.Draft, priority bool) error {
	body, err := json.Marshal(map[string]any{
		"draft_id":   d.ID.String(),
		"agent_id":   d.AgentID.String(),
		"trend_id":   d.TrendID,
		"match_id":   d.MatchID,
		"title":      d.Title,
		"summary":    d.Summary,
		"highlights": d.Highlights,
		"charts":     d.Charts,
		"metadata":   d.Metadata,
		"priority":   priority,
		"created_at": d.CreatedAt.Format(time.RFC3339),
	})
	if err != nil {
		return fmt.Errorf("redisstream: marshal draft: %w", err)
	}
	return q.client.XAdd(ctx, &goredis.XAddArgs{
		Stream: queueName,
		MaxLen: q.maxLen,
		Approx: true,
		Values: map[string]any{
			"draft_id": d.ID.String(),
			"priority": fmt.Sprintf("%t", priority),
			"payload":  body,
		},
	}).Err()
}

func (q *Queue) Depth(ctx context.Context, queueName string) (int64, error) {
	return q.client.XLen(ctx, queueName).Result()
}

func (q *Queue) Close() error { return q.client.Close() }
