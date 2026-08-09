// Package publishworker — the READ side of the per-agent publishing
// queues.
//
//	trend pipeline ──enqueue──► insight:queue:nexus:{agent} ──► this worker
//	                                                              │
//	                                              publisher.Publish (LLM …)
//
// WHY IT EXISTS. Publication used to run inline inside the trend consumer,
// immediately after the enqueue. Two consequences followed:
//
//  1. Nothing ever read the queues. They grew until MaxLen trimmed their
//     oldest entries, and the "active jobs" gauge reported a number that
//     could only rise.
//  2. One agent's slow LLM call stalled the whole trend stream. The worst
//     case is one timeout per provider, per agent, per trend — with the
//     next trend waiting behind all of it.
//
// Moving publication here makes the queue real: the trend handler returns
// as soon as the draft is durable and queued, and each agent's backlog
// drains on its own goroutine.
//
// WHAT THE HANDOFF GUARANTEES. The trend is acknowledged only after the
// draft row, the candidate row and the queue entry are all durable. A crash
// between enqueue and publish loses nothing: the queue entry is unacked and
// is redelivered.
package publishworker

import (
	"context"
	"time"

	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/application/publisher"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// Worker drains every enabled agent's publishing queue.
type Worker struct {
	agents    ports.AgentRepository
	consumer  ports.DraftQueueConsumer
	publisher *publisher.Engine
	logger    zerolog.Logger
	// refresh — how often the agent set is re-read. Agents are editable
	// at runtime, so a queue set resolved once at boot would never pick
	// up an agent created afterwards.
	refresh time.Duration
}

func New(
	agents ports.AgentRepository,
	consumer ports.DraftQueueConsumer,
	engine *publisher.Engine,
	refresh time.Duration,
	logger zerolog.Logger,
) *Worker {
	if refresh <= 0 {
		refresh = time.Minute
	}
	return &Worker{
		agents: agents, consumer: consumer, publisher: engine,
		refresh: refresh, logger: logger,
	}
}

// Run blocks until ctx is cancelled.
func (w *Worker) Run(ctx context.Context) {
	var current []string
	var cancelConsume context.CancelFunc
	defer func() {
		if cancelConsume != nil {
			cancelConsume()
		}
	}()

	ticker := time.NewTicker(w.refresh)
	defer ticker.Stop()

	for {
		queues, err := w.queueNames(ctx)
		if err != nil {
			w.logger.Warn().Err(err).Msg("publish_worker_agent_list_failed")
		} else if !sameSet(current, queues) {
			// Restart consumption against the new set. Cancelling first
			// means an in-flight publish finishes its Redis ACK before the
			// goroutine goes away; an unacked entry is simply redelivered.
			if cancelConsume != nil {
				cancelConsume()
			}
			consumeCtx, cancel := context.WithCancel(ctx)
			cancelConsume = cancel
			current = queues
			w.logger.Info().
				Strs("queues", queues).
				Msg("publish_worker_consuming")
			go func(c context.Context, names []string) {
				if err := w.consumer.Consume(c, names, w.handle); err != nil &&
					c.Err() == nil {
					w.logger.Error().Err(err).Msg("publish_worker_consume_stopped")
				}
			}(consumeCtx, queues)
		}

		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// handle publishes one queued draft.
//
// Only INFRASTRUCTURE failures are returned, and only those leave the entry
// unacked for redelivery. A suppressed, invalid or ticketed candidate is a
// product outcome the publisher already recorded — retrying it would burn
// the same LLM budget to reach the same conclusion, and an anti-spam
// suppression would never stop being true.
func (w *Worker) handle(ctx context.Context, item ports.QueuedDraft) error {
	_, err := w.publisher.Publish(ctx, publisher.Input{
		Draft:    item.Draft,
		Context:  item.Context,
		Decision: item.Decision,
	})
	return err
}

func (w *Worker) queueNames(ctx context.Context) ([]string, error) {
	agents, err := w.agents.List(ctx)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(agents))
	for _, a := range agents {
		// Disabled agents keep their queue: a draft already queued was
		// approved by a decision taken while the agent was live, and
		// dropping it would lose work without recording why. Nothing new
		// is routed to them, so the backlog drains and stops.
		names = append(names, a.QueueName())
	}
	return names, nil
}

func sameSet(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	seen := make(map[string]struct{}, len(a))
	for _, v := range a {
		seen[v] = struct{}{}
	}
	for _, v := range b {
		if _, ok := seen[v]; !ok {
			return false
		}
	}
	return true
}
