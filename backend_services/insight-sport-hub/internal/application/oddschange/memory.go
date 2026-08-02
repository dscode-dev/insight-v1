package oddschange

import (
	"context"
	"sync"
	"time"
)

// MemoryStore is an in-memory LastOddsStore for tests + single-instance
// deployments. The production multi-instance gate uses the
// Redis-backed store in internal/adapters/redisinfra so the
// last-published baseline is shared across pods.
type MemoryStore struct {
	mu    sync.Mutex
	last  map[string]map[string]float64
	clock func() time.Time
	exp   map[string]time.Time
}

func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		last:  map[string]map[string]float64{},
		exp:   map[string]time.Time{},
		clock: time.Now,
	}
}

func (s *MemoryStore) Get(_ context.Context, key string) (map[string]float64, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if exp, ok := s.exp[key]; ok && s.clock().After(exp) {
		delete(s.last, key)
		delete(s.exp, key)
	}
	v, ok := s.last[key]
	if !ok {
		return nil, false, nil
	}
	cp := make(map[string]float64, len(v))
	for k, val := range v {
		cp[k] = val
	}
	return cp, true, nil
}

func (s *MemoryStore) Put(_ context.Context, key string, prices map[string]float64, ttl time.Duration) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := make(map[string]float64, len(prices))
	for k, v := range prices {
		cp[k] = v
	}
	s.last[key] = cp
	if ttl > 0 {
		s.exp[key] = s.clock().Add(ttl)
	}
	return nil
}
