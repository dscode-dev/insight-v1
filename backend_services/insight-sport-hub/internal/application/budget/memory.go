package budget

import (
	"context"
	"sync"
	"time"
)

// MemoryStore is an in-memory CounterStore for single-instance
// deployments + tests. TTLs are honoured lazily (expired keys read as
// zero). The production multi-instance path uses the Redis-backed
// store in internal/adapters/redisinfra.
type MemoryStore struct {
	mu     sync.Mutex
	counts map[string]int64
	expiry map[string]time.Time
	clock  func() time.Time
}

func NewMemoryStore(clock func() time.Time) *MemoryStore {
	if clock == nil {
		clock = time.Now
	}
	return &MemoryStore{
		counts: map[string]int64{},
		expiry: map[string]time.Time{},
		clock:  clock,
	}
}

func (s *MemoryStore) Increment(_ context.Context, key string, ttl time.Duration) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gcLocked(key)
	s.counts[key]++
	if ttl > 0 {
		s.expiry[key] = s.clock().Add(ttl)
	}
	return s.counts[key], nil
}

func (s *MemoryStore) Count(_ context.Context, key string) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gcLocked(key)
	return s.counts[key], nil
}

func (s *MemoryStore) gcLocked(key string) {
	if exp, ok := s.expiry[key]; ok && s.clock().After(exp) {
		delete(s.counts, key)
		delete(s.expiry, key)
	}
}
