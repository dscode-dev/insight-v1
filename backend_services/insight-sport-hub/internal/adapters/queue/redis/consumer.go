// Consumer half of the Redis Streams adapter — XREADGROUP / XACK
// helpers. Kept as small free functions so the RedisQueue type in
// queue.go stays a thin orchestrator.
package redis

import (
	"context"
	"errors"
	"fmt"
	"time"

	goredis "github.com/redis/go-redis/v9"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// xreadGroupOne reads up to ONE new message from the configured
// stream + consumer group, blocking up to cfg.BlockTimeout. Returns
// (id, payload-map, err).
//
// Block timeout vs ctx semantics: BLOCK is enforced server-side by
// Redis; ctx is enforced client-side by go-redis. ctx.Done() unblocks
// the call regardless of BLOCK — that's the lever the queue's
// Dequeue uses for fast shutdown.
func xreadGroupOne(
	ctx context.Context, client goredis.Cmdable, cfg Config,
) (string, map[string]any, error) {
	res, err := client.XReadGroup(ctx, &goredis.XReadGroupArgs{
		Group:    cfg.Group,
		Consumer: cfg.ConsumerName,
		Streams:  []string{cfg.Stream, ">"},
		Count:    1,
		Block:    cfg.BlockTimeout,
	}).Result()
	if err != nil {
		// `redis.Nil` is the "BLOCK timed out, no messages" path.
		// Surface it untyped so the caller can decide to retry.
		if errors.Is(err, goredis.Nil) {
			return "", nil, errBlockTimeout
		}
		return "", nil, fmt.Errorf("redis queue: XREADGROUP: %w", err)
	}
	if len(res) == 0 || len(res[0].Messages) == 0 {
		return "", nil, errBlockTimeout
	}
	msg := res[0].Messages[0]
	return msg.ID, msg.Values, nil
}

// errBlockTimeout is internal — the queue's Dequeue loops on it.
// Never surfaces to callers (translated to context errors or
// returned as a ports.Delivery).
var errBlockTimeout = errors.New("redis queue: block timeout")

// ack — XACK + best-effort XDEL to drop the entry. XACK alone clears
// the pending list; XDEL frees the stream slot.
func ack(ctx context.Context, client goredis.Cmdable, cfg Config, id string) error {
	if err := client.XAck(ctx, cfg.Stream, cfg.Group, id).Err(); err != nil {
		return fmt.Errorf("redis queue: XACK: %w", err)
	}
	// XDEL is best-effort. A failed XDEL leaves a tombstone but
	// doesn't break ack semantics.
	_ = client.XDel(ctx, cfg.Stream, id).Err()
	return nil
}

// streamDepth returns XLEN of the main stream. Used by the Stats
// reporter.
func streamDepth(ctx context.Context, client goredis.Cmdable, cfg Config) int64 {
	v, err := client.XLen(ctx, cfg.Stream).Result()
	if err != nil {
		return 0
	}
	return v
}

// pendingCount returns XPENDING summary count for the group.
func pendingCount(ctx context.Context, client goredis.Cmdable, cfg Config) int64 {
	res, err := client.XPending(ctx, cfg.Stream, cfg.Group).Result()
	if err != nil || res == nil {
		return 0
	}
	return res.Count
}

// retryDepth returns ZCARD of the retry sorted set.
func retryDepth(ctx context.Context, client goredis.Cmdable, cfg Config) int64 {
	v, err := client.ZCard(ctx, cfg.RetryZSet).Result()
	if err != nil {
		return 0
	}
	return v
}

// consumersCount counts active consumers in the group via
// XINFO CONSUMERS.
func consumersCount(ctx context.Context, client goredis.Cmdable, cfg Config) int64 {
	res, err := client.XInfoConsumers(ctx, cfg.Stream, cfg.Group).Result()
	if err != nil {
		return 0
	}
	return int64(len(res))
}

// pingTimeout — fail-loud sentinel for connection probes.
const pingTimeout = 2 * time.Second

// pingHealthy returns true when PING succeeds within pingTimeout.
func pingHealthy(ctx context.Context, client goredis.Cmdable) bool {
	pctx, cancel := context.WithTimeout(ctx, pingTimeout)
	defer cancel()
	return client.Ping(pctx).Err() == nil
}

// sanityCheckPortRef — guarantees the ports import stays used even
// if other functions are gofmt-trimmed.
var _ = ports.QueueStats{}

// deliveryFromClaim — builds a ports.Delivery from a decoded job +
// the Redis stream entry id the claimer is about to dead-letter.
// Used only inside the redis package (claimer.go).
func deliveryFromClaim(job syncdom.SyncJob, entryID string) ports.Delivery {
	return ports.Delivery{
		Job:      job,
		Attempt:  job.CurrentAttempt + 1,
		AckToken: entryID,
	}
}
