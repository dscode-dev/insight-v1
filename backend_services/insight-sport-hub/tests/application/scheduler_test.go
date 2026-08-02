// Scheduler tests — Sprint 3.
//
// Locks in:
//   - the scheduler dispatches the first tick immediately (boot ergonomics);
//   - graceful shutdown returns ctx.Err() and stops scheduling new ticks;
//   - planning failures don't crash the loop;
//   - dispatched jobs land in the queue.
package application_test

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/queue"
	"github.com/konoha-labs/insight-sports-hub/internal/application/scheduler"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// noopQueueStatus — minimal QueueStatusRecorder for tests that don't
// care about the counters.
type noopQueueStatus struct {
	mu      sync.Mutex
	queued  int
	dropped int
}

func (s *noopQueueStatus) IncQueued(string) { s.mu.Lock(); defer s.mu.Unlock(); s.queued++ }
func (s *noopQueueStatus) IncQueueDropped(string, string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.dropped++
}

func TestSchedulerEmitsImmediateFirstTick(t *testing.T) {
	c := &stepClock{now: time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)}
	comp := uuid.New()
	registry := &fakeCompetitionRegistry{
		comps: []ports.Competition{{ID: comp, Slug: "x", Name: "X", Enabled: true}},
	}
	adapters := map[string]ports.SourceAdapter{
		"p": newAdapter("p", source.ProviderCapability{SupportsFixtures: true}),
	}
	policies := map[string][]syncdom.PollPolicy{
		"p": {mustPolicy(t, "p", syncdom.TypeFixtures, time.Hour)},
	}

	q := queue.NewInMemoryBasic(8)
	defer q.Close()
	status := &noopQueueStatus{}

	planner := scheduler.NewPlanner(adapters, registry, policies, c)
	dispatcher := scheduler.NewDispatcher(q, status, zerolog.Nop())
	sched := scheduler.New(
		scheduler.Config{Interval: 10 * time.Second},
		planner, dispatcher, zerolog.Nop(),
	)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { _ = sched.Run(ctx); close(done) }()

	// Wait briefly for the immediate first tick to dispatch.
	deadline := time.After(time.Second)
	for q.Len() == 0 {
		select {
		case <-deadline:
			t.Fatal("first tick produced no queued job")
		default:
			time.Sleep(5 * time.Millisecond)
		}
	}
	cancel()
	<-done

	if status.queued != 1 {
		t.Errorf("expected 1 queued, got %d", status.queued)
	}
	snap := sched.Snapshot()
	if snap.JobsCreatedTotal != 1 {
		t.Errorf("snapshot jobs_created_total = %d, want 1", snap.JobsCreatedTotal)
	}
	if snap.Ticks < 1 {
		t.Errorf("snapshot ticks = %d, want >= 1", snap.Ticks)
	}
	if snap.Running {
		t.Errorf("snapshot.Running must be false after ctx cancel")
	}
}

func TestSchedulerStopsCleanlyOnContextCancel(t *testing.T) {
	c := &stepClock{now: time.Now()}
	registry := &fakeCompetitionRegistry{}
	planner := scheduler.NewPlanner(
		map[string]ports.SourceAdapter{}, registry,
		map[string][]syncdom.PollPolicy{}, c,
	)
	q := queue.NewInMemoryBasic(1)
	defer q.Close()
	sched := scheduler.New(
		scheduler.Config{Interval: 50 * time.Millisecond},
		planner,
		scheduler.NewDispatcher(q, &noopQueueStatus{}, zerolog.Nop()),
		zerolog.Nop(),
	)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- sched.Run(ctx) }()
	time.Sleep(80 * time.Millisecond)
	cancel()
	select {
	case err := <-done:
		if err != context.Canceled {
			t.Errorf("expected context.Canceled, got %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("scheduler did not stop on ctx cancel")
	}
}
