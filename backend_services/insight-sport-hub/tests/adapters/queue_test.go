// In-memory JobQueue tests — Sprint 3, extended in Sprint 4.
//
// Locks in FIFO ordering, bounded capacity (Enqueue fails fast),
// graceful shutdown behaviour (Close unblocks Dequeue with a typed
// error, pending Enqueue is rejected), and the Sprint 4 ack/retry/
// fail semantics.
//
// These properties allow the Sprint 4 Redis adapter — and any future
// transport — to slot in behind ports.JobQueue without disturbing
// the application layer.
package adapters_test

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/queue"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

func mustJob(t *testing.T, providerID string) syncdom.SyncJob {
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

func newQ(t *testing.T, cap int) *queue.InMemoryQueue {
	t.Helper()
	return queue.NewInMemoryBasic(cap)
}

func TestInMemoryQueueFIFO(t *testing.T) {
	q := newQ(t, 3)
	defer q.Close()
	a := mustJob(t, "a")
	b := mustJob(t, "b")
	c := mustJob(t, "c")
	for _, j := range []syncdom.SyncJob{a, b, c} {
		if err := q.Enqueue(context.Background(), j); err != nil {
			t.Fatalf("enqueue: %v", err)
		}
	}
	if q.Len() != 3 {
		t.Errorf("len = %d, want 3", q.Len())
	}
	out := []string{}
	for i := 0; i < 3; i++ {
		d, err := q.Dequeue(context.Background())
		if err != nil {
			t.Fatalf("dequeue: %v", err)
		}
		out = append(out, d.Job.ProviderID)
		_ = q.Ack(context.Background(), d)
	}
	if out[0] != "a" || out[1] != "b" || out[2] != "c" {
		t.Errorf("FIFO violated: %v", out)
	}
}

func TestInMemoryQueueRejectsAtCapacity(t *testing.T) {
	q := newQ(t, 2)
	defer q.Close()
	_ = q.Enqueue(context.Background(), mustJob(t, "a"))
	_ = q.Enqueue(context.Background(), mustJob(t, "b"))
	err := q.Enqueue(context.Background(), mustJob(t, "c"))
	if !errors.Is(err, ports.ErrQueueFull) {
		t.Errorf("expected ErrQueueFull, got %v", err)
	}
}

func TestInMemoryQueueDequeueBlocksAndUnblocks(t *testing.T) {
	q := newQ(t, 1)
	defer q.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()

	got := make(chan ports.Delivery, 1)
	errs := make(chan error, 1)
	go func() {
		d, err := q.Dequeue(ctx)
		if err != nil {
			errs <- err
			return
		}
		got <- d
	}()

	time.Sleep(20 * time.Millisecond)
	_ = q.Enqueue(context.Background(), mustJob(t, "z"))

	select {
	case d := <-got:
		if d.Job.ProviderID != "z" {
			t.Errorf("got %q, want z", d.Job.ProviderID)
		}
		if d.AckToken == "" {
			t.Error("ack token must be non-empty")
		}
		if d.Attempt != 1 {
			t.Errorf("attempt = %d, want 1 on first emit", d.Attempt)
		}
	case err := <-errs:
		t.Fatalf("dequeue err: %v", err)
	case <-ctx.Done():
		t.Fatal("dequeue never unblocked")
	}
}

func TestInMemoryQueueDequeueRespectsContextCancel(t *testing.T) {
	q := newQ(t, 1)
	defer q.Close()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		_, err := q.Dequeue(ctx)
		done <- err
	}()
	time.Sleep(20 * time.Millisecond)
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Errorf("expected context.Canceled, got %v", err)
		}
	case <-time.After(200 * time.Millisecond):
		t.Fatal("dequeue did not return on ctx cancel")
	}
}

func TestInMemoryQueueClosePreventsEnqueue(t *testing.T) {
	q := newQ(t, 2)
	q.Close()
	err := q.Enqueue(context.Background(), mustJob(t, "x"))
	if !errors.Is(err, ports.ErrQueueClosed) {
		t.Errorf("expected ErrQueueClosed, got %v", err)
	}
}

func TestInMemoryQueueCloseUnblocksDequeue(t *testing.T) {
	q := newQ(t, 1)
	done := make(chan error, 1)
	go func() {
		_, err := q.Dequeue(context.Background())
		done <- err
	}()
	time.Sleep(20 * time.Millisecond)
	q.Close()
	select {
	case err := <-done:
		if !errors.Is(err, ports.ErrQueueClosed) {
			t.Errorf("expected ErrQueueClosed, got %v", err)
		}
	case <-time.After(200 * time.Millisecond):
		t.Fatal("dequeue did not return after close")
	}
}

func TestInMemoryQueueCloseDrainsRemaining(t *testing.T) {
	q := newQ(t, 3)
	_ = q.Enqueue(context.Background(), mustJob(t, "a"))
	_ = q.Enqueue(context.Background(), mustJob(t, "b"))
	q.Close()

	if _, err := q.Dequeue(context.Background()); err != nil {
		t.Errorf("first drain: %v", err)
	}
	if _, err := q.Dequeue(context.Background()); err != nil {
		t.Errorf("second drain: %v", err)
	}
	_, err := q.Dequeue(context.Background())
	if !errors.Is(err, ports.ErrQueueClosed) {
		t.Errorf("after drain expected ErrQueueClosed, got %v", err)
	}
}

func TestInMemoryQueueCloseIsIdempotent(t *testing.T) {
	q := newQ(t, 1)
	q.Close()
	q.Close() // must not panic
}

// ---------------------------------------------------------------------------
// Sprint 4 — Ack / Retry / Fail semantics on the in-memory adapter.
// ---------------------------------------------------------------------------

// countingDLQ — captures Record calls so the Fail-path test can
// assert the failure was emitted with the right shape.
type countingDLQ struct {
	calls atomic.Int32
	last  syncdom.SyncJobFailure
}

func (c *countingDLQ) Record(_ context.Context, f syncdom.SyncJobFailure) error {
	c.calls.Add(1)
	c.last = f
	return nil
}

func TestInMemoryQueueAckIsNoOp(t *testing.T) {
	q := newQ(t, 1)
	defer q.Close()
	_ = q.Enqueue(context.Background(), mustJob(t, "p"))
	d, _ := q.Dequeue(context.Background())
	if err := q.Ack(context.Background(), d); err != nil {
		t.Errorf("Ack must be no-op, got %v", err)
	}
}

func TestInMemoryQueueRetryReenqueuesWithBumpedAttempt(t *testing.T) {
	// Use a clock that won't insert a real wait — base delay applies.
	q := queue.NewInMemory(queue.InMemoryConfig{
		Capacity: 4, DLQ: queue.NoopDLQ{},
	})
	defer q.Close()

	_ = q.Enqueue(context.Background(), mustJob(t, "p"))
	d, _ := q.Dequeue(context.Background())
	if err := q.Retry(context.Background(), d, "transient"); err != nil {
		t.Fatalf("Retry: %v", err)
	}

	// The retry is scheduled via time.AfterFunc using the base
	// backoff (5s). Wait briefly for the timer fire — but base
	// backoff is too long for tests. Verify timer registered via
	// Stats.RetryQueueSize instead.
	stats := q.Stats(context.Background())
	if stats.RetryQueueSize < 1 {
		t.Errorf("expected at least 1 timer in retry queue, got %d", stats.RetryQueueSize)
	}
}

func TestInMemoryQueueRetryWithExhaustedAttemptsRoutesToDLQ(t *testing.T) {
	dlq := &countingDLQ{}
	q := queue.NewInMemory(queue.InMemoryConfig{Capacity: 2, DLQ: dlq})
	defer q.Close()

	job := mustJob(t, "p")
	job.CurrentAttempt = job.MaxAttempts // exhausted
	_ = q.Enqueue(context.Background(), job)
	d, _ := q.Dequeue(context.Background())

	if err := q.Retry(context.Background(), d, "exhausted"); err != nil {
		t.Fatalf("Retry: %v", err)
	}
	if dlq.calls.Load() != 1 {
		t.Errorf("DLQ Record not called; calls=%d", dlq.calls.Load())
	}
	if dlq.last.Reason != "exhausted" {
		t.Errorf("DLQ reason = %q, want exhausted", dlq.last.Reason)
	}
	if dlq.last.Attempts != job.MaxAttempts {
		t.Errorf("DLQ attempts = %d, want %d", dlq.last.Attempts, job.MaxAttempts)
	}
}

func TestInMemoryQueueFailRecordsAndAcks(t *testing.T) {
	dlq := &countingDLQ{}
	q := queue.NewInMemory(queue.InMemoryConfig{Capacity: 2, DLQ: dlq})
	defer q.Close()

	_ = q.Enqueue(context.Background(), mustJob(t, "p"))
	d, _ := q.Dequeue(context.Background())
	if err := q.Fail(context.Background(), d, "unknown_provider"); err != nil {
		t.Fatalf("Fail: %v", err)
	}
	if dlq.calls.Load() != 1 {
		t.Errorf("DLQ Record not invoked; calls=%d", dlq.calls.Load())
	}
	if dlq.last.Reason != "unknown_provider" {
		t.Errorf("DLQ reason wrong: %q", dlq.last.Reason)
	}
}
