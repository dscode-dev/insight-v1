// Publication handoff — the trend pipeline enqueues, a separate worker
// publishes.
//
// Before this split, `HandleTrend` called the publication engine inline: the
// queues were written and never read, and one agent's LLM latency stalled
// the whole trend stream. These tests pin the new contract from both sides.
package application_test

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-nexus/internal/adapters/inmemory"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// --- write side ---------------------------------------------------------

// The queued item must be self-contained: draft AND the context and decision
// that produced it. Carrying only the draft would force the worker to
// rebuild the context later, from memories that have since moved on.
func TestQueuedDraftCarriesContextAndDecision(t *testing.T) {
	p, agents, _, _, _, queue, _ := newPipeline(t)
	officialAgents(t, agents)

	ev := trendEvent("momentum_shift", "pulse")
	if _, err := p.HandleTrend(context.Background(),
		trend.Envelope{SchemaVersion: "v3", Trend: ev}); err != nil {
		t.Fatal(err)
	}

	items := queuedEverywhere(queue, agents)
	if len(items) == 0 {
		t.Fatal("nothing was enqueued")
	}
	for _, item := range items {
		if item.Draft.ID == uuid.Nil {
			t.Fatal("queued item has no draft")
		}
		if item.Context.ClusterID == uuid.Nil {
			t.Fatal("queued item lost the cluster context")
		}
		if item.Context.Agent.Name == "" {
			t.Fatal("queued item lost the agent — the persona lookup needs it")
		}
		if item.Decision.Action == "" {
			t.Fatal("queued item lost the decision that authorised it")
		}
		if item.Context.Trend.TrendID != ev.TrendID {
			t.Fatalf("queued trend = %q, want %q",
				item.Context.Trend.TrendID, ev.TrendID)
		}
	}
}

// The trend handler must not wait on publication. It returns as soon as the
// work is durably queued.
func TestHandleTrendDoesNotPublish(t *testing.T) {
	p, agents, _, _, pubs, queue, metrics := newPipeline(t)
	officialAgents(t, agents)

	start := time.Now()
	if _, err := p.HandleTrend(context.Background(), trend.Envelope{
		SchemaVersion: "v3", Trend: trendEvent("momentum_shift", "pulse"),
	}); err != nil {
		t.Fatal(err)
	}
	elapsed := time.Since(start)

	// No LLM, no Social client is reachable from the pipeline at all now;
	// this asserts the shape rather than the clock, but a handler that
	// still published would have to have been given those dependencies.
	if elapsed > 2*time.Second {
		t.Fatalf("HandleTrend took %s — it is doing more than queueing", elapsed)
	}
	if len(queuedEverywhere(queue, agents)) == 0 {
		t.Fatal("the draft was never queued")
	}
	if metrics.candidateCount() == 0 {
		t.Fatal("no publication candidate recorded")
	}
	// The candidate row is written BEFORE the queue entry, so the worker
	// can never publish against a row that does not exist.
	if len(pubs.All()) == 0 {
		t.Fatal("candidate row missing")
	}
}

// --- read side ----------------------------------------------------------

// A handler failure must leave the work queued. Publication costs an LLM
// call and can reach Social; losing an entry on a transient database error
// would drop a post nobody knows was owed.
func TestFailedPublishKeepsWorkQueued(t *testing.T) {
	queue := inmemory.NewQueue()
	item := ports.QueuedDraft{}
	item.Draft.ID = uuid.New()
	if err := queue.Enqueue(context.Background(), "q:test", item); err != nil {
		t.Fatal(err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	boom := errors.New("postgres down")
	err := queue.Consume(ctx, []string{"q:test"},
		func(context.Context, ports.QueuedDraft) error { return boom })
	if !errors.Is(err, boom) {
		t.Fatalf("Consume err = %v, want the handler error", err)
	}
	if got := len(queue.Items("q:test")); got != 1 {
		t.Fatalf("queued after failure = %d, want 1 (work must not be lost)", got)
	}
}

func TestSuccessfulPublishDrainsTheQueue(t *testing.T) {
	queue := inmemory.NewQueue()
	for i := 0; i < 3; i++ {
		item := ports.QueuedDraft{}
		item.Draft.ID = uuid.New()
		if err := queue.Enqueue(context.Background(), "q:test", item); err != nil {
			t.Fatal(err)
		}
	}

	var mu sync.Mutex
	handled := 0
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	_ = queue.Consume(ctx, []string{"q:test"},
		func(context.Context, ports.QueuedDraft) error {
			mu.Lock()
			handled++
			mu.Unlock()
			return nil
		})

	if handled != 3 {
		t.Fatalf("handled = %d, want 3", handled)
	}
	if got := len(queue.Items("q:test")); got != 0 {
		t.Fatalf("queue depth after draining = %d, want 0", got)
	}
}

// --- helpers ------------------------------------------------------------

func queuedEverywhere(q *inmemory.Queue, agents *inmemory.AgentRepo) []ports.QueuedDraft {
	list, err := agents.List(context.Background())
	if err != nil {
		return nil
	}
	var out []ports.QueuedDraft
	for _, a := range list {
		out = append(out, q.Items(a.QueueName())...)
	}
	return out
}

func (m *stubMetrics) candidateCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	total := 0
	for _, n := range m.candidates {
		total += n
	}
	return total
}
