// Package competition — in-memory adapter for ports.CompetitionRegistry.
//
// Sprint 2 introduced the Postgres-backed adapter; this one stays
// for unit tests + the "no DB available" fallback path. The
// extended port methods (Sprint 2) are implemented as in-memory
// maps over the same struct shapes.
//
// Permissive mode means: IsKnown returns true even for ids not
// registered when the allow-list is empty (Sprint 1 compat). Strict
// mode demands explicit registration.
package competition

import (
	"context"
	"sync"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

type InMemory struct {
	mu         sync.RWMutex
	allowed    map[uuid.UUID]ports.Competition
	externals  map[externalKey]uuid.UUID
	permissive bool
}

type externalKey struct {
	sourceID   string
	externalID string
}

// New returns a permissive registry — accepts every competition id
// until Register is called or PermissiveMode is flipped.
func New() *InMemory {
	return &InMemory{
		allowed:    map[uuid.UUID]ports.Competition{},
		externals:  map[externalKey]uuid.UUID{},
		permissive: true,
	}
}

// NewStrict returns a registry that rejects everything until
// Register is called. Use in tests + Sprint 2 production (the
// Postgres adapter is the real production path).
func NewStrict() *InMemory {
	return &InMemory{
		allowed:    map[uuid.UUID]ports.Competition{},
		externals:  map[externalKey]uuid.UUID{},
		permissive: false,
	}
}

// Allow is kept for backwards compatibility with the Sprint 1
// API — registers a barebones competition under a generated slug.
func (r *InMemory) Allow(id uuid.UUID) {
	_ = r.Register(context.Background(), ports.Competition{
		ID:      id,
		Slug:    id.String(),
		Name:    "<unnamed>",
		Enabled: true,
	})
}

func (r *InMemory) IsKnown(_ context.Context, id uuid.UUID) (bool, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	if r.permissive && len(r.allowed) == 0 {
		return true, nil
	}
	c, ok := r.allowed[id]
	return ok && c.Enabled, nil
}

func (r *InMemory) Register(_ context.Context, c ports.Competition) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, dup := r.allowed[c.ID]; dup {
		return ports.ErrDuplicate
	}
	r.allowed[c.ID] = c
	return nil
}

func (r *InMemory) Lookup(_ context.Context, id uuid.UUID) (ports.Competition, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	c, ok := r.allowed[id]
	if !ok {
		return ports.Competition{}, ports.ErrNotFound
	}
	return c, nil
}

func (r *InMemory) LookupByExternalID(
	_ context.Context, sourceID, externalID string,
) (ports.Competition, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	canonicalID, ok := r.externals[externalKey{sourceID, externalID}]
	if !ok {
		return ports.Competition{}, ports.ErrNotFound
	}
	c, ok := r.allowed[canonicalID]
	if !ok {
		return ports.Competition{}, ports.ErrNotFound
	}
	return c, nil
}

func (r *InMemory) LinkExternalID(
	_ context.Context, competitionID uuid.UUID, sourceID, externalID string,
) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.externals[externalKey{sourceID, externalID}] = competitionID
	return nil
}

func (r *InMemory) GetExternalIDForSource(
	_ context.Context, competitionID uuid.UUID, sourceID string,
) (string, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	// Reverse-scan the externals map. Cheap because the registry
	// holds at most a few dozen competitions; the access pattern is
	// per-adapter call, not per-event.
	for k, v := range r.externals {
		if v == competitionID && k.sourceID == sourceID {
			return k.externalID, nil
		}
	}
	return "", ports.ErrNotFound
}

func (r *InMemory) SetEnabled(_ context.Context, id uuid.UUID, enabled bool) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	c, ok := r.allowed[id]
	if !ok {
		return ports.ErrNotFound
	}
	c.Enabled = enabled
	r.allowed[id] = c
	return nil
}

func (r *InMemory) List(_ context.Context) ([]ports.Competition, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]ports.Competition, 0, len(r.allowed))
	for _, c := range r.allowed {
		out = append(out, c)
	}
	return out, nil
}
