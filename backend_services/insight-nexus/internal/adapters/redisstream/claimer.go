// Claimer — pending-message recovery + dead-lettering (Sprint 3.5).
//
// Mirrors the reliability level Atlas's consumer already has:
//
//   - pending entries idle past MinIdle are claimed (XPENDING+XCLAIM)
//     and re-dispatched through the same handler path;
//   - entries whose delivery count exceeded MaxDeliveries move to the
//     DLQ stream (insight:dlq:nexus) with {payload, error, attempts,
//     agent} preserved, then ACK so they never redeliver.
//
// The claim pass runs inside the consumer loop on a time gate, so a
// crashed sibling consumer's pending entries are recovered without a
// separate worker process.
package redisstream

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	goredis "github.com/redis/go-redis/v9"

	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
)

var (
	pendingClaimedTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "nexus_pending_claimed_total",
		Help: "Pending trend-stream entries claimed for retry.",
	})
	dlqTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "nexus_dlq_total",
		Help: "Trend-stream entries dead-lettered after exhausting deliveries.",
	})
	retriesTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "nexus_retries_total",
		Help: "Handler retries executed on claimed pending entries.",
	})
	poisonTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "nexus_poison_messages_total",
		Help: "Undecodable trend-stream entries dead-lettered (never discarded).",
	}, []string{"reason"})
)

// poison dead-letters one undecodable entry (V1.1 poison policy:
// DLQ first, ACK only after the DLQ write succeeds — a failed DLQ
// write leaves the entry pending so nothing is ever silently lost).
func (c *Consumer) poison(ctx context.Context, msg goredis.XMessage, payload string, derr error) {
	reason := "malformed_json"
	if errors.Is(derr, trend.ErrUnsupportedSchema) {
		reason = "unsupported_schema"
	}
	body, _ := json.Marshal(map[string]any{
		"payload": payload,
		"error":   derr.Error(),
		"reason":  reason,
	})
	if err := c.client.XAdd(ctx, &goredis.XAddArgs{
		Stream: c.cfg.Claimer.DLQStream,
		Values: map[string]any{
			"source_entry_id": msg.ID,
			"kind":            "poison",
			"reason":          reason,
			"payload":         body,
		},
	}).Err(); err != nil {
		c.logger.Error().Err(err).
			Str("entry_id", msg.ID).
			Msg("nexus_poison_dlq_xadd_failed")
		return // keep pending; better stuck than lost.
	}
	_ = c.client.XAck(ctx, c.cfg.Stream, c.cfg.Group, msg.ID).Err()
	poisonTotal.WithLabelValues(reason).Inc()
	c.logger.Warn().Err(derr).
		Str("entry_id", msg.ID).
		Str("reason", reason).
		Str("dlq", c.cfg.Claimer.DLQStream).
		Msg("nexus_trend_poisoned")
}

// ClaimerConfig — pending recovery knobs (all env-configurable).
type ClaimerConfig struct {
	Enabled       bool
	MinIdle       time.Duration
	Interval      time.Duration
	MaxDeliveries int64
	DLQStream     string
}

func (c ClaimerConfig) defaults() ClaimerConfig {
	if c.MinIdle <= 0 {
		c.MinIdle = 30 * time.Second
	}
	if c.Interval <= 0 {
		c.Interval = 15 * time.Second
	}
	if c.MaxDeliveries <= 0 {
		c.MaxDeliveries = 8
	}
	if c.DLQStream == "" {
		c.DLQStream = "insight:dlq:nexus"
	}
	return c
}

// reclaimPending runs one claim pass: dead-letter exhausted entries,
// claim + re-dispatch the rest.
func (c *Consumer) reclaimPending(ctx context.Context, handler Handler) {
	pending, err := c.client.XPendingExt(ctx, &goredis.XPendingExtArgs{
		Stream: c.cfg.Stream,
		Group:  c.cfg.Group,
		Idle:   c.cfg.Claimer.MinIdle,
		Start:  "-",
		End:    "+",
		Count:  64,
	}).Result()
	if err != nil {
		if err != goredis.Nil {
			c.logger.Warn().Err(err).Msg("nexus_claimer_xpending_failed")
		}
		return
	}
	for _, entry := range pending {
		if entry.RetryCount > c.cfg.Claimer.MaxDeliveries {
			c.deadLetter(ctx, entry)
			continue
		}
		claimed, err := c.client.XClaim(ctx, &goredis.XClaimArgs{
			Stream:   c.cfg.Stream,
			Group:    c.cfg.Group,
			Consumer: c.cfg.Consumer,
			MinIdle:  c.cfg.Claimer.MinIdle,
			Messages: []string{entry.ID},
		}).Result()
		if err != nil && err != goredis.Nil {
			c.logger.Warn().Err(err).
				Str("entry_id", entry.ID).
				Msg("nexus_claimer_xclaim_failed")
			continue
		}
		for _, msg := range claimed {
			pendingClaimedTotal.Inc()
			retriesTotal.Inc()
			c.dispatch(ctx, msg, handler)
		}
	}
}

// deadLetter moves one exhausted entry to the DLQ, preserving the
// payload, the failure context and the producing agent, then ACKs it
// so it never redelivers.
func (c *Consumer) deadLetter(ctx context.Context, entry goredis.XPendingExt) {
	// Claim it (ownership required before reading + acking).
	claimed, err := c.client.XClaim(ctx, &goredis.XClaimArgs{
		Stream:   c.cfg.Stream,
		Group:    c.cfg.Group,
		Consumer: c.cfg.Consumer,
		MinIdle:  c.cfg.Claimer.MinIdle,
		Messages: []string{entry.ID},
	}).Result()
	if err != nil && err != goredis.Nil {
		c.logger.Warn().Err(err).
			Str("entry_id", entry.ID).
			Msg("nexus_dlq_claim_failed")
		return
	}
	payload := ""
	agent := ""
	if len(claimed) > 0 {
		payload, _ = claimed[0].Values["payload"].(string)
		if env, derr := trend.DecodeEnvelope([]byte(payload)); derr == nil {
			agent = env.Trend.Agent
		}
	}
	body, _ := json.Marshal(map[string]any{
		"payload":  payload,
		"error":    "max_deliveries_exceeded",
		"attempts": entry.RetryCount,
		"agent":    agent,
	})
	if err := c.client.XAdd(ctx, &goredis.XAddArgs{
		Stream: c.cfg.Claimer.DLQStream,
		Values: map[string]any{
			"source_entry_id": entry.ID,
			"attempts":        entry.RetryCount,
			"payload":         body,
		},
	}).Err(); err != nil {
		c.logger.Error().Err(err).
			Str("entry_id", entry.ID).
			Msg("nexus_dlq_xadd_failed")
		return // keep pending; better stuck than lost.
	}
	_ = c.client.XAck(ctx, c.cfg.Stream, c.cfg.Group, entry.ID).Err()
	dlqTotal.Inc()
	c.logger.Warn().
		Str("entry_id", entry.ID).
		Int64("attempts", entry.RetryCount).
		Str("dlq", c.cfg.Claimer.DLQStream).
		Msg("nexus_entry_dead_lettered")
}
