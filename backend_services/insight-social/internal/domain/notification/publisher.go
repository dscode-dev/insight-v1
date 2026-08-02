package notification

import "context"

// Publisher is the SINGLE seam through which notifications are created. Event
// producers across the platform depend on THIS interface, never on the repo or
// a concrete service — so the delivery mechanism can evolve (direct write today
// → outbox → Kafka → SSE) without any producer changing.
//
// Invariant (no cascade): one user action must produce AT MOST one notification
// per recipient. Producers achieve this with a deterministic DedupKey; the
// Publisher/repo enforce it via ON CONFLICT DO NOTHING.
type Publisher interface {
	// Publish creates one notification. Idempotent: a duplicate dedup_key is a
	// no-op success (delivered=false). Never returns an error for a duplicate.
	Publish(ctx context.Context, n *Notification) (delivered bool, err error)
}

// DirectPublisher is the V1 implementation: a synchronous write straight to the
// repository. Swap for an OutboxPublisher / stream publisher later without
// touching producers.
type DirectPublisher struct {
	repo Repository
}

func NewDirectPublisher(repo Repository) *DirectPublisher { return &DirectPublisher{repo: repo} }

func (p *DirectPublisher) Publish(ctx context.Context, n *Notification) (bool, error) {
	return p.repo.Insert(ctx, n)
}
