//go:build integration

// Redis Streams adapter integration tests — Sprint 4.
//
// Build-tagged with `integration` so the default `go test ./...`
// run doesn't depend on miniredis being installed. CI flips the
// flag once go.sum is hydrated; local lab runs:
//
//	go test -tags integration ./tests/adapters/...
//
// Validates against an in-process miniredis instance — no real
// Redis required.
package adapters_test

import (
	"context"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/queue"
	queueredis "github.com/konoha-labs/insight-sports-hub/internal/adapters/queue/redis"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

func startMini(t *testing.T) *miniredis.Miniredis {
	t.Helper()
	s := miniredis.RunT(t)
	return s
}

func newRedisQueue(t *testing.T, addr string) *queueredis.RedisQueue {
	t.Helper()
	q, err := queueredis.New(context.Background(),
		queueredis.Config{
			Addr:         addr,
			Stream:       "insight:test:syncjobs",
			Group:        "insight-test",
			ConsumerName: "test-consumer-1",
			RetryZSet:    "insight:test:retry",
			MaxLen:       100,
			BlockTimeout: 200 * time.Millisecond,
		},
		queue.NoopDLQ{},
		zerolog.Nop(),
	)
	if err != nil {
		t.Fatalf("redis queue new: %v", err)
	}
	return q
}

func redisJob(t *testing.T, providerID string) syncdom.SyncJob {
	t.Helper()
	job, err := syncdom.NewSyncJob(
		syncdom.NewJobID(), providerID, uuid.New(),
		syncdom.TypeFixtures, syncdom.PriorityNormal,
		time.Now(), nil,
	)
	if err != nil {
		t.Fatalf("build job: %v", err)
	}
	return job
}

func TestRedisQueueRoundTrip(t *testing.T) {
	s := startMini(t)
	q := newRedisQueue(t, s.Addr())
	defer q.Close()

	job := redisJob(t, "api_football")
	if err := q.Enqueue(context.Background(), job); err != nil {
		t.Fatalf("enqueue: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	d, err := q.Dequeue(ctx)
	if err != nil {
		t.Fatalf("dequeue: %v", err)
	}
	if d.Job.JobID != job.JobID {
		t.Errorf("round-trip job id lost: got %v, want %v", d.Job.JobID, job.JobID)
	}
	if d.Job.ProviderID != "api_football" {
		t.Errorf("provider id lost: %q", d.Job.ProviderID)
	}
	if d.AckToken == "" {
		t.Error("ack token must be non-empty")
	}
}

func TestRedisQueueAckRemovesPending(t *testing.T) {
	s := startMini(t)
	q := newRedisQueue(t, s.Addr())
	defer q.Close()

	_ = q.Enqueue(context.Background(), redisJob(t, "p"))
	d, err := q.Dequeue(context.Background())
	if err != nil {
		t.Fatalf("dequeue: %v", err)
	}
	if err := q.Ack(context.Background(), d); err != nil {
		t.Errorf("ack: %v", err)
	}
	stats := q.Stats(context.Background())
	if stats.PendingMessages != 0 {
		t.Errorf("expected zero pending after ack, got %d", stats.PendingMessages)
	}
}

func TestRedisQueueRetryRoutesToRetryZSet(t *testing.T) {
	s := startMini(t)
	q := newRedisQueue(t, s.Addr())
	defer q.Close()

	_ = q.Enqueue(context.Background(), redisJob(t, "p"))
	d, err := q.Dequeue(context.Background())
	if err != nil {
		t.Fatalf("dequeue: %v", err)
	}
	if err := q.Retry(context.Background(), d, "transient"); err != nil {
		t.Fatalf("retry: %v", err)
	}
	stats := q.Stats(context.Background())
	if stats.RetryQueueSize < 1 {
		t.Errorf("retry zset should contain 1 entry, got %d", stats.RetryQueueSize)
	}
}

func TestRedisQueueFailRecordsAndAcks(t *testing.T) {
	s := startMini(t)
	dlq := &countingDLQ{}
	q, err := queueredis.New(context.Background(),
		queueredis.Config{
			Addr:         s.Addr(),
			Stream:       "insight:test:syncjobs",
			Group:        "insight-test",
			ConsumerName: "test-consumer-fail",
			RetryZSet:    "insight:test:retry",
			MaxLen:       100,
			BlockTimeout: 200 * time.Millisecond,
		}, dlq, zerolog.Nop(),
	)
	if err != nil {
		t.Fatalf("new: %v", err)
	}
	defer q.Close()

	_ = q.Enqueue(context.Background(), redisJob(t, "p"))
	d, err := q.Dequeue(context.Background())
	if err != nil {
		t.Fatalf("dequeue: %v", err)
	}
	if err := q.Fail(context.Background(), d, "exhausted"); err != nil {
		t.Errorf("fail: %v", err)
	}
	if dlq.calls.Load() != 1 {
		t.Errorf("DLQ not called; calls=%d", dlq.calls.Load())
	}
}

func TestRedisQueueRetainsExhaustedAttemptsViaFail(t *testing.T) {
	s := startMini(t)
	dlq := &countingDLQ{}
	q, _ := queueredis.New(context.Background(),
		queueredis.Config{
			Addr: s.Addr(), Stream: "insight:test:syncjobs",
			Group: "insight-test", ConsumerName: "test-consumer-exh",
			RetryZSet: "insight:test:retry", MaxLen: 100,
			BlockTimeout: 200 * time.Millisecond,
		}, dlq, zerolog.Nop(),
	)
	defer q.Close()

	job := redisJob(t, "p")
	job.CurrentAttempt = job.MaxAttempts
	_ = q.Enqueue(context.Background(), job)
	d, _ := q.Dequeue(context.Background())
	// Retry on an exhausted job promotes to Fail internally.
	_ = q.Retry(context.Background(), d, "transient_but_exhausted")
	if dlq.calls.Load() != 1 {
		t.Errorf("expected DLQ call on exhausted retry, got %d", dlq.calls.Load())
	}
}

func TestRedisQueueConsumerGroupSemantics(t *testing.T) {
	s := startMini(t)
	q1 := newRedisQueue(t, s.Addr())
	defer q1.Close()

	cfg := queueredis.Config{
		Addr: s.Addr(), Stream: "insight:test:syncjobs",
		Group: "insight-test", ConsumerName: "test-consumer-2",
		RetryZSet: "insight:test:retry", MaxLen: 100,
		BlockTimeout: 200 * time.Millisecond,
	}
	q2, err := queueredis.New(context.Background(), cfg,
		queue.NoopDLQ{}, zerolog.Nop())
	if err != nil {
		t.Fatalf("second consumer: %v", err)
	}
	defer q2.Close()

	// Publish two jobs; the two consumers must split, not duplicate.
	_ = q1.Enqueue(context.Background(), redisJob(t, "a"))
	_ = q1.Enqueue(context.Background(), redisJob(t, "b"))

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	d1, err := q1.Dequeue(ctx)
	if err != nil {
		t.Fatalf("q1 dequeue: %v", err)
	}
	d2, err := q2.Dequeue(ctx)
	if err != nil {
		t.Fatalf("q2 dequeue: %v", err)
	}
	if d1.Job.JobID == d2.Job.JobID {
		t.Errorf("consumer group violated — both consumers got the same job %v", d1.Job.JobID)
	}
}

func TestRedisQueueCloseIsIdempotent(t *testing.T) {
	s := startMini(t)
	q := newRedisQueue(t, s.Addr())
	q.Close()
	q.Close() // must not panic
}

// Compile-time guard: the Redis adapter must continue to satisfy
// ports.JobQueue + ports.StatsReporter — the entire point of the
// sprint.
var (
	_ ports.JobQueue      = (*queueredis.RedisQueue)(nil)
	_ ports.StatsReporter = (*queueredis.RedisQueue)(nil)
)
