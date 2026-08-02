// Producer half of the Redis Streams adapter — XADD encoding of
// SyncJob into stream entries.
//
// Wire format: a single stream-entry field "payload" holding the
// JSON-encoded SyncJob. Adding fields stays backward compatible
// because consumers ignore unknown ones.
package redis

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	goredis "github.com/redis/go-redis/v9"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// payloadField — the single key used in the stream entry's
// field/value map. Centralised so producer + consumer agree.
const payloadField = "payload"

// encodeJob serialises a SyncJob to the stream-entry field map.
// Uses encoding/json for portability — every language that may
// consume the stream in the future (Python admin tooling, …) has a
// JSON codec.
func encodeJob(job syncdom.SyncJob) (map[string]any, error) {
	body, err := json.Marshal(job)
	if err != nil {
		return nil, fmt.Errorf("redis queue: encode job: %w", err)
	}
	return map[string]any{payloadField: body}, nil
}

// decodeJob parses a SyncJob out of the field/value map XREADGROUP
// returns.
func decodeJob(values map[string]any) (syncdom.SyncJob, error) {
	raw, ok := values[payloadField]
	if !ok {
		return syncdom.SyncJob{}, errors.New("redis queue: missing payload field")
	}
	var body []byte
	switch v := raw.(type) {
	case string:
		body = []byte(v)
	case []byte:
		body = v
	default:
		return syncdom.SyncJob{}, fmt.Errorf("redis queue: unsupported payload type %T", raw)
	}
	var job syncdom.SyncJob
	if err := json.Unmarshal(body, &job); err != nil {
		return syncdom.SyncJob{}, fmt.Errorf("redis queue: decode job: %w", err)
	}
	return job, nil
}

// xadd publishes a job to the stream with MAXLEN trimming. Returns
// the stream entry id (acts as the AckToken in the runner's eyes).
func xadd(ctx context.Context, client goredis.Cmdable, cfg Config, job syncdom.SyncJob) (string, error) {
	values, err := encodeJob(job)
	if err != nil {
		return "", err
	}
	id, err := client.XAdd(ctx, &goredis.XAddArgs{
		Stream: cfg.Stream,
		MaxLen: cfg.MaxLen,
		Approx: true,
		Values: values,
	}).Result()
	if err != nil {
		return "", fmt.Errorf("redis queue: XADD: %w", err)
	}
	return id, nil
}

// zaddRetry stores a job in the retry sorted set. Score is the
// unix-nano timestamp at which the retry becomes eligible.
func zaddRetry(ctx context.Context, client goredis.Cmdable, cfg Config, job syncdom.SyncJob) error {
	if job.RetryAfter.IsZero() {
		return errors.New("redis queue: retry job missing RetryAfter")
	}
	body, err := json.Marshal(job)
	if err != nil {
		return fmt.Errorf("redis queue: encode retry: %w", err)
	}
	score := float64(job.RetryAfter.UnixNano())
	return client.ZAdd(ctx, cfg.RetryZSet, goredis.Z{
		Score:  score,
		Member: string(body),
	}).Err()
}

// promoteReadyRetries scans the retry sorted set for entries whose
// score (== retry-after unix nano) is now <= the supplied `at`, then
// XADDs each back to the main stream + removes from the zset.
//
// This is what the queue's background promoter goroutine calls.
//
// Bounded to `limit` per pass — keeps the call cheap under load.
// Returns the number of jobs promoted.
func promoteReadyRetries(
	ctx context.Context, client goredis.Cmdable, cfg Config,
	at time.Time, limit int64,
) (int, error) {
	max := fmt.Sprintf("%d", at.UnixNano())
	members, err := client.ZRangeByScore(ctx, cfg.RetryZSet, &goredis.ZRangeBy{
		Min: "-inf", Max: max, Count: limit,
	}).Result()
	if err != nil {
		return 0, fmt.Errorf("redis queue: zrange retry: %w", err)
	}
	if len(members) == 0 {
		return 0, nil
	}
	promoted := 0
	for _, m := range members {
		var job syncdom.SyncJob
		if err := json.Unmarshal([]byte(m), &job); err != nil {
			// Skip + remove malformed entries. Don't block the
			// healthy ones.
			_ = client.ZRem(ctx, cfg.RetryZSet, m).Err()
			continue
		}
		if _, err := xadd(ctx, client, cfg, job); err != nil {
			// XADD failed (e.g. Redis hiccup). Leave the entry in
			// the zset; the next tick retries.
			continue
		}
		if err := client.ZRem(ctx, cfg.RetryZSet, m).Err(); err == nil {
			promoted++
		}
	}
	return promoted, nil
}

// ensureGroup creates the consumer group + the stream if either is
// missing. Safe to call repeatedly (idempotent via MKSTREAM +
// detecting "BUSYGROUP").
func ensureGroup(ctx context.Context, client goredis.Cmdable, cfg Config) error {
	err := client.XGroupCreateMkStream(ctx, cfg.Stream, cfg.Group, "$").Err()
	if err == nil {
		return nil
	}
	// go-redis surfaces "BUSYGROUP" as the bare message; tolerate.
	if isBusyGroup(err) {
		return nil
	}
	return fmt.Errorf("redis queue: XGROUP CREATE: %w", err)
}

func isBusyGroup(err error) bool {
	if err == nil {
		return false
	}
	return containsAny(err.Error(), "BUSYGROUP", "Consumer Group name already exists")
}

func containsAny(s string, needles ...string) bool {
	for _, n := range needles {
		if indexOf(s, n) >= 0 {
			return true
		}
	}
	return false
}

// indexOf — tiny strings.Contains substitute; avoids importing the
// strings package just for this hot-path check.
func indexOf(s, sub string) int {
	if len(sub) == 0 {
		return 0
	}
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

// sanityCheckPort — compile-time guard that ports.ErrQueueFull is
// imported (helps the linter from sweeping the import if the file
// shrinks).
var _ = ports.ErrQueueFull
