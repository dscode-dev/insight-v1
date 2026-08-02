// Settle routing tests — Sprint 5.
//
// Verifies the in-memory queue routes Settle(reason) through the
// FailureType classifier:
//   - retryable reasons → Retry path (timer scheduled / DLQ untouched)
//   - non-retryable reasons → Fail path (DLQ Record invoked)
package adapters_test

import (
	"context"
	"testing"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/queue"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

func TestSettleValidationGoesToDLQ(t *testing.T) {
	dlq := &countingDLQ{}
	q := queue.NewInMemory(queue.InMemoryConfig{Capacity: 2, DLQ: dlq})
	defer q.Close()

	_ = q.Enqueue(context.Background(), mustJob(t, "p"))
	d, _ := q.Dequeue(context.Background())
	if err := q.Settle(context.Background(), d, syncdom.ReasonMalformedPayload); err != nil {
		t.Fatalf("Settle: %v", err)
	}
	if dlq.calls.Load() != 1 {
		t.Errorf("validation failure should route to DLQ; calls=%d", dlq.calls.Load())
	}
	if dlq.last.Reason != syncdom.ReasonMalformedPayload {
		t.Errorf("DLQ reason = %q, want %q", dlq.last.Reason, syncdom.ReasonMalformedPayload)
	}
}

func TestSettlePermanentGoesToDLQ(t *testing.T) {
	dlq := &countingDLQ{}
	q := queue.NewInMemory(queue.InMemoryConfig{Capacity: 2, DLQ: dlq})
	defer q.Close()

	_ = q.Enqueue(context.Background(), mustJob(t, "p"))
	d, _ := q.Dequeue(context.Background())
	if err := q.Settle(context.Background(), d, syncdom.ReasonCompetitionOff); err != nil {
		t.Fatalf("Settle: %v", err)
	}
	if dlq.calls.Load() != 1 {
		t.Errorf("permanent failure should route to DLQ; calls=%d", dlq.calls.Load())
	}
}

func TestSettleTransientSchedulesRetry(t *testing.T) {
	dlq := &countingDLQ{}
	q := queue.NewInMemory(queue.InMemoryConfig{Capacity: 4, DLQ: dlq})
	defer q.Close()

	_ = q.Enqueue(context.Background(), mustJob(t, "p"))
	d, _ := q.Dequeue(context.Background())
	if err := q.Settle(context.Background(), d, syncdom.ReasonProviderTimeout); err != nil {
		t.Fatalf("Settle: %v", err)
	}
	if dlq.calls.Load() != 0 {
		t.Errorf("transient failure must NOT route to DLQ; calls=%d", dlq.calls.Load())
	}
	stats := q.Stats(context.Background())
	if stats.RetryQueueSize < 1 {
		t.Errorf("expected at least 1 timer queued, got %d", stats.RetryQueueSize)
	}
}

func TestSettleInfrastructureSchedulesRetry(t *testing.T) {
	dlq := &countingDLQ{}
	q := queue.NewInMemory(queue.InMemoryConfig{Capacity: 4, DLQ: dlq})
	defer q.Close()

	_ = q.Enqueue(context.Background(), mustJob(t, "p"))
	d, _ := q.Dequeue(context.Background())
	if err := q.Settle(context.Background(), d, syncdom.ReasonRedisUnavailable); err != nil {
		t.Fatalf("Settle: %v", err)
	}
	if dlq.calls.Load() != 0 {
		t.Errorf("infrastructure failure must NOT route to DLQ; calls=%d", dlq.calls.Load())
	}
}
