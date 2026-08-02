// FEATURE-COMMUNITIES-V1 Stage 2 — small in-memory TTL cache for the
// USER-INDEPENDENT community stats projection (member/discussion counts +
// role distribution). Keyed by community id only: stats carry no per-user
// data, so the entry is safely shared across viewers. Viewer-specific parts of
// the detail (viewer_role, membership_status, capabilities) are NEVER cached.
//
// Bounded + swept on write; when full of live entries, new writes skip caching
// rather than evict unpredictably (determinism over hit-rate). The interface is
// deliberately tiny so a Redis impl can replace it without touching handlers.
package communitybff

import (
	"encoding/json"
	"sync"
	"time"
)

// cachedStats is the user-independent slice of the detail that is safe to
// share across viewers. Encoded/decoded here so the aggregator stays clean.
type cachedStats struct {
	RoleCounts      RoleCounts `json:"role_counts"`
	MemberCount     int64      `json:"member_count"`
	DiscussionCount int64      `json:"discussion_count"`
}

func encodeCacheStats(rc RoleCounts, memberCount, discussionCount int64) []byte {
	b, _ := json.Marshal(cachedStats{RoleCounts: rc, MemberCount: memberCount, DiscussionCount: discussionCount})
	return b
}

func decodeCachedStats(body []byte) (RoleCounts, int64, int64, bool) {
	var s cachedStats
	if err := json.Unmarshal(body, &s); err != nil {
		return RoleCounts{}, 0, 0, false
	}
	return s.RoleCounts, s.MemberCount, s.DiscussionCount, true
}

type statsEntry struct {
	body      []byte
	expiresAt time.Time
}

type StatsCache struct {
	mu      sync.Mutex
	entries map[string]statsEntry
	ttl     time.Duration
	maxSize int
	now     func() time.Time
}

func NewStatsCache(ttl time.Duration, maxSize int) *StatsCache {
	return &StatsCache{
		entries: make(map[string]statsEntry),
		ttl:     ttl,
		maxSize: maxSize,
		now:     time.Now,
	}
}

func (c *StatsCache) Get(communityID string) ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.entries[communityID]
	if !ok || c.now().After(e.expiresAt) {
		if ok {
			delete(c.entries, communityID)
		}
		return nil, false
	}
	return e.body, true
}

func (c *StatsCache) Set(communityID string, body []byte) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.entries) >= c.maxSize {
		now := c.now()
		for k, e := range c.entries {
			if now.After(e.expiresAt) {
				delete(c.entries, k)
			}
		}
		if len(c.entries) >= c.maxSize {
			return
		}
	}
	c.entries[communityID] = statsEntry{body: body, expiresAt: c.now().Add(c.ttl)}
}
