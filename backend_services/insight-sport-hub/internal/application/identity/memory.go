package identity

import (
	"context"
	"sync"
	"time"

	"github.com/google/uuid"
)

// MemoryRegistry is an in-process Registry. The Hub uses it to stamp a
// best-effort canonical_match_id onto canonical events; Atlas owns the
// authoritative persistent registry. Deterministic minting (see Mint)
// keeps ids reproducible across processes for identical inputs, so the
// in-memory scope is acceptable for the Hub's hint.
type MemoryRegistry struct {
	mu      sync.Mutex
	aliases map[string]uuid.UUID // "provider|external" → canonical
	byComp  map[uuid.UUID][]CanonicalMatch
}

func NewMemoryRegistry() *MemoryRegistry {
	return &MemoryRegistry{
		aliases: map[string]uuid.UUID{},
		byComp:  map[uuid.UUID][]CanonicalMatch{},
	}
}

func aliasKey(provider, externalID string) string { return provider + "|" + externalID }

func (m *MemoryRegistry) AliasLookup(_ context.Context, provider, externalID string) (uuid.UUID, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	id, ok := m.aliases[aliasKey(provider, externalID)]
	return id, ok, nil
}

func (m *MemoryRegistry) FindWithinTolerance(
	_ context.Context, competitionID uuid.UUID,
	normHome, normAway string, kickoff time.Time, tol time.Duration,
) (CanonicalMatch, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, cm := range m.byComp[competitionID] {
		if cm.HomeTeam != normHome || cm.AwayTeam != normAway {
			continue
		}
		if absDuration(cm.Kickoff.Sub(kickoff.UTC())) <= tol {
			return cm, true, nil
		}
	}
	return CanonicalMatch{}, false, nil
}

func (m *MemoryRegistry) Save(_ context.Context, match CanonicalMatch, alias MatchAlias) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.aliases[aliasKey(alias.Provider, alias.ExternalID)] = alias.CanonicalMatchID
	existing := m.byComp[match.CompetitionID]
	for _, cm := range existing {
		if cm.CanonicalMatchID == match.CanonicalMatchID {
			return nil // already recorded
		}
	}
	m.byComp[match.CompetitionID] = append(existing, match)
	return nil
}

func absDuration(d time.Duration) time.Duration {
	if d < 0 {
		return -d
	}
	return d
}
