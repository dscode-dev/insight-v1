// Runner Ack/Retry/Fail interaction tests — Sprint 4.
//
// These verify the lifecycle the spec requires:
//   - successful job → Ack
//   - transient failure (fetch/ratelimit) → Retry
//   - terminal failure (unknown provider) → Fail
//
// Uses a hand-rolled recording-queue stub rather than the real
// in-memory queue so we can observe which lifecycle method was
// called per delivery.
package application_test

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-sports-hub/internal/application/jobrunner"
	"github.com/konoha-labs/insight-sports-hub/internal/application/ratelimit"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// recordingQueue — pushes a single delivery once, then blocks
// forever on subsequent Dequeue calls until ctx is cancelled.
// Records which lifecycle method the runner invoked.
type recordingQueue struct {
	mu       sync.Mutex
	served   bool
	delivery ports.Delivery

	ackCalls    atomic.Int32
	retryCalls  atomic.Int32
	failCalls   atomic.Int32
	lastReason  string
	lastAcked   string
	lastRetried string
	lastFailed  string
}

func (q *recordingQueue) Enqueue(_ context.Context, _ syncdom.SyncJob) error { return nil }
func (q *recordingQueue) Dequeue(ctx context.Context) (ports.Delivery, error) {
	q.mu.Lock()
	if !q.served {
		q.served = true
		d := q.delivery
		q.mu.Unlock()
		return d, nil
	}
	q.mu.Unlock()
	<-ctx.Done()
	return ports.Delivery{}, ctx.Err()
}
func (q *recordingQueue) Ack(_ context.Context, d ports.Delivery) error {
	q.ackCalls.Add(1)
	q.lastAcked = d.AckToken
	return nil
}
func (q *recordingQueue) Retry(_ context.Context, d ports.Delivery, reason string) error {
	q.retryCalls.Add(1)
	q.lastRetried = d.AckToken
	q.lastReason = reason
	return nil
}
func (q *recordingQueue) Fail(_ context.Context, d ports.Delivery, reason string) error {
	q.failCalls.Add(1)
	q.lastFailed = d.AckToken
	q.lastReason = reason
	return nil
}

// Settle — Sprint 5. Mirrors the real adapter routing so the
// runner-Ack tests still pass: classify reason → Retry or Fail.
func (q *recordingQueue) Settle(ctx context.Context, d ports.Delivery, reason string) error {
	ft := syncdom.ClassifyReason(reason)
	if !ft.Retryable() {
		return q.Fail(ctx, d, reason)
	}
	return q.Retry(ctx, d, reason)
}

func (q *recordingQueue) Len() int { return 0 }
func (q *recordingQueue) Close()   {}

func makeDelivery(t *testing.T, providerID string) ports.Delivery {
	t.Helper()
	job, err := syncdom.NewSyncJob(
		syncdom.NewJobID(), providerID, uuid.New(),
		syncdom.TypeFixtures, syncdom.PriorityNormal,
		time.Now(), nil,
	)
	if err != nil {
		t.Fatalf("build job: %v", err)
	}
	return ports.Delivery{Job: job, Attempt: 1, AckToken: "tok-" + providerID}
}

func runUntil(t *testing.T, q *recordingQueue, runner *jobrunner.Runner, predicate func() bool) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go runner.Run(ctx)
	deadline := time.After(time.Second)
	for {
		if predicate() {
			return
		}
		select {
		case <-deadline:
			t.Fatalf("predicate never satisfied; q=%+v", q)
		default:
			time.Sleep(5 * time.Millisecond)
		}
	}
}

func TestRunnerAcksOnHappyPath(t *testing.T) {
	q := &recordingQueue{delivery: makeDelivery(t, "p")}
	stub := &stubAdapter{
		identity: ports.AdapterIdentity{SourceID: "p"},
		fixturesFn: func() ([]*event.RawSportsEvent, error) {
			return []*event.RawSportsEvent{makeRaw(t, "p")}, nil
		},
	}
	limiter := ratelimit.NewSliding(&stepClock{now: time.Now()})
	runner := jobrunner.New(
		jobrunner.Config{Workers: 1}, q,
		map[string]ports.SourceAdapter{"p": stub}, limiter,
		func(_ context.Context, _ *event.RawSportsEvent) error { return nil },
		newStubStatus(), zerolog.Nop(),
	)
	runUntil(t, q, runner, func() bool { return q.ackCalls.Load() == 1 })

	if q.retryCalls.Load() != 0 || q.failCalls.Load() != 0 {
		t.Errorf("happy path must not call Retry/Fail; q=%+v", q)
	}
}

func TestRunnerRetriesOnFetchError(t *testing.T) {
	q := &recordingQueue{delivery: makeDelivery(t, "p")}
	stub := &stubAdapter{
		identity: ports.AdapterIdentity{SourceID: "p"},
		fixturesFn: func() ([]*event.RawSportsEvent, error) {
			return nil, errors.New("upstream 503")
		},
	}
	limiter := ratelimit.NewSliding(&stepClock{now: time.Now()})
	runner := jobrunner.New(
		jobrunner.Config{Workers: 1}, q,
		map[string]ports.SourceAdapter{"p": stub}, limiter,
		func(_ context.Context, _ *event.RawSportsEvent) error { return nil },
		newStubStatus(), zerolog.Nop(),
	)
	runUntil(t, q, runner, func() bool { return q.retryCalls.Load() == 1 })

	if q.ackCalls.Load() != 0 || q.failCalls.Load() != 0 {
		t.Errorf("fetch error must Retry only; q=%+v", q)
	}
	if q.lastReason != syncdom.ReasonProviderError {
		t.Errorf("retry reason = %q, want %q", q.lastReason, syncdom.ReasonProviderError)
	}
}

func TestRunnerFailsOnUnknownProvider(t *testing.T) {
	q := &recordingQueue{delivery: makeDelivery(t, "ghost")}
	limiter := ratelimit.NewSliding(&stepClock{now: time.Now()})
	runner := jobrunner.New(
		jobrunner.Config{Workers: 1}, q,
		map[string]ports.SourceAdapter{}, limiter,
		func(_ context.Context, _ *event.RawSportsEvent) error { return nil },
		newStubStatus(), zerolog.Nop(),
	)
	runUntil(t, q, runner, func() bool { return q.failCalls.Load() == 1 })

	if q.ackCalls.Load() != 0 || q.retryCalls.Load() != 0 {
		t.Errorf("unknown provider must Fail only; q=%+v", q)
	}
	if q.lastReason != "unknown_provider" {
		t.Errorf("fail reason = %q, want unknown_provider", q.lastReason)
	}
}

func TestRunnerRetriesOnRateLimit(t *testing.T) {
	q := &recordingQueue{delivery: makeDelivery(t, "p")}
	stub := &stubAdapter{
		identity: ports.AdapterIdentity{SourceID: "p"},
		fixturesFn: func() ([]*event.RawSportsEvent, error) {
			t.Fatal("adapter must NOT be called when rate-limited")
			return nil, nil
		},
	}
	limiter := ratelimit.NewSliding(&stepClock{now: time.Now()})
	policy, _ := syncdom.NewRateLimitPolicy("p", 1, 0, 0, 100)
	limiter.SetPolicy(policy)
	limiter.Allow("p") // pre-burn the budget

	runner := jobrunner.New(
		jobrunner.Config{Workers: 1}, q,
		map[string]ports.SourceAdapter{"p": stub}, limiter,
		func(_ context.Context, _ *event.RawSportsEvent) error { return nil },
		newStubStatus(), zerolog.Nop(),
	)
	runUntil(t, q, runner, func() bool { return q.retryCalls.Load() == 1 })

	if q.lastReason != syncdom.ReasonProviderRateLimit {
		t.Errorf("retry reason = %q, want %q", q.lastReason, syncdom.ReasonProviderRateLimit)
	}
}
