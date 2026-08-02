// In-memory Sprint 4 repositories — tests + lab composition.
package inmemory

import (
	"context"
	"sort"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-nexus/internal/application/antispam"
	"github.com/konoha-labs/insight-nexus/internal/domain/persona"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// ---- PersonaRepository -------------------------------------------------------

type PersonaRepo struct {
	mu       sync.RWMutex
	personas map[string]persona.AgentPersona
}

// NewPersonaRepo starts seeded with the five official personas (the
// same defaults the migration seeds).
func NewPersonaRepo() *PersonaRepo {
	r := &PersonaRepo{personas: map[string]persona.AgentPersona{}}
	for _, p := range persona.Defaults() {
		r.personas[p.Slug] = p
	}
	return r
}

func (r *PersonaRepo) Get(_ context.Context, slug string) (persona.AgentPersona, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	p, ok := r.personas[slug]
	if !ok {
		return persona.AgentPersona{}, ports.ErrNotFound
	}
	return p, nil
}

func (r *PersonaRepo) List(_ context.Context) ([]persona.AgentPersona, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]persona.AgentPersona, 0, len(r.personas))
	for _, p := range r.personas {
		out = append(out, p)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Slug < out[j].Slug })
	return out, nil
}

func (r *PersonaRepo) Upsert(_ context.Context, p persona.AgentPersona) error {
	if err := p.Validate(); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.personas[p.Slug] = p
	return nil
}

// ---- CandidateRepository -------------------------------------------------------

type CandidateRepo struct {
	mu         sync.RWMutex
	candidates []publication.Candidate
}

func NewCandidateRepo() *CandidateRepo { return &CandidateRepo{} }

func (r *CandidateRepo) Save(_ context.Context, c publication.Candidate) error {
	if err := c.Validate(); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	for i := range r.candidates {
		if r.candidates[i].ID == c.ID {
			r.candidates[i] = c
			return nil
		}
	}
	r.candidates = append(r.candidates, c)
	return nil
}

func (r *CandidateRepo) List(
	_ context.Context, status publication.CandidateStatus, limit int,
) ([]publication.Candidate, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]publication.Candidate, 0, limit)
	for _, c := range r.candidates {
		if status == "" || c.Status == status {
			out = append(out, c)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt.After(out[j].CreatedAt)
	})
	if len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}

func (r *CandidateRepo) History(ctx context.Context, limit int) ([]publication.Candidate, error) {
	return r.List(ctx, publication.CandidatePublished, limit)
}

func (r *CandidateRepo) AgentCounts(_ context.Context) (map[string]map[string]int, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := map[string]map[string]int{}
	for _, c := range r.candidates {
		agent := out[c.AgentName]
		if agent == nil {
			agent = map[string]int{}
			out[c.AgentName] = agent
		}
		agent[string(c.Status)]++
	}
	return out, nil
}

// ---- TicketRepository ---------------------------------------------------------------

type TicketRepo struct {
	mu      sync.RWMutex
	tickets map[uuid.UUID]publication.Ticket
}

func NewTicketRepo() *TicketRepo {
	return &TicketRepo{tickets: map[uuid.UUID]publication.Ticket{}}
}

func (r *TicketRepo) Save(_ context.Context, t publication.Ticket) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.tickets[t.ID] = t
	return nil
}

func (r *TicketRepo) Get(_ context.Context, id uuid.UUID) (publication.Ticket, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	t, ok := r.tickets[id]
	if !ok {
		return publication.Ticket{}, ports.ErrNotFound
	}
	return t, nil
}

func (r *TicketRepo) List(
	_ context.Context, status publication.TicketStatus, limit int,
) ([]publication.Ticket, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]publication.Ticket, 0, limit)
	for _, t := range r.tickets {
		if status == "" || t.Status == status {
			out = append(out, t)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt.After(out[j].CreatedAt)
	})
	if len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}

// ---- antispam.Log -----------------------------------------------------------------------

type SpamLog struct {
	mu      sync.RWMutex
	entries []antispam.Entry
}

func NewSpamLog() *SpamLog { return &SpamLog{} }

func (l *SpamLog) Record(_ context.Context, e antispam.Entry) error {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.entries = append(l.entries, e)
	return nil
}

func (l *SpamLog) last(match func(antispam.Entry) bool) time.Time {
	l.mu.RLock()
	defer l.mu.RUnlock()
	var newest time.Time
	for _, e := range l.entries {
		if match(e) && e.PublishedAt.After(newest) {
			newest = e.PublishedAt
		}
	}
	return newest
}

func (l *SpamLog) LastByAgent(_ context.Context, agentID uuid.UUID) (time.Time, error) {
	return l.last(func(e antispam.Entry) bool { return e.AgentID == agentID }), nil
}

func (l *SpamLog) LastByCluster(_ context.Context, clusterID uuid.UUID) (time.Time, error) {
	return l.last(func(e antispam.Entry) bool { return e.ClusterID == clusterID }), nil
}

func (l *SpamLog) LastByTrend(_ context.Context, trendID string) (time.Time, error) {
	return l.last(func(e antispam.Entry) bool { return e.TrendID == trendID }), nil
}

func (l *SpamLog) LastByAgentMatch(_ context.Context, agentID uuid.UUID, matchID string) (time.Time, error) {
	return l.last(func(e antispam.Entry) bool {
		return e.AgentID == agentID && e.MatchID == matchID
	}), nil
}

func (l *SpamLog) CountByAgentSince(_ context.Context, agentID uuid.UUID, since time.Time) (int, error) {
	l.mu.RLock()
	defer l.mu.RUnlock()
	n := 0
	for _, e := range l.entries {
		if e.AgentID == agentID && e.PublishedAt.After(since) {
			n++
		}
	}
	return n, nil
}

// Compile-time conformance.
var (
	_ ports.PersonaRepository   = (*PersonaRepo)(nil)
	_ ports.CandidateRepository = (*CandidateRepo)(nil)
	_ ports.TicketRepository    = (*TicketRepo)(nil)
	_ antispam.Log              = (*SpamLog)(nil)
)

// ---- AuditRepository (Sprint 4.5) -----------------------------------------------

type AuditRepo struct {
	mu     sync.RWMutex
	events []publication.AuditEvent
}

func NewAuditRepo() *AuditRepo { return &AuditRepo{} }

func (r *AuditRepo) Record(_ context.Context, e publication.AuditEvent) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.events = append(r.events, e)
	return nil
}

func (r *AuditRepo) List(_ context.Context, f ports.AuditFilter) ([]publication.AuditEvent, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	limit := f.Limit
	if limit <= 0 {
		limit = 100
	}
	out := make([]publication.AuditEvent, 0, limit)
	for _, e := range r.events {
		if f.Actor != "" && e.Actor != f.Actor {
			continue
		}
		if f.Action != "" && e.Action != f.Action {
			continue
		}
		if f.EntityType != "" && e.EntityType != f.EntityType {
			continue
		}
		if f.EntityID != "" && e.EntityID != f.EntityID {
			continue
		}
		out = append(out, e)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt.After(out[j].CreatedAt)
	})
	if len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}

var _ ports.AuditRepository = (*AuditRepo)(nil)
