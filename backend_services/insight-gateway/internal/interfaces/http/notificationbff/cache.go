// FEATURE-NOTIFICATIONS-V1 Stage 2 — unread-count cache ONLY.
//
// We deliberately do NOT cache the list (it changes too often). Only the
// per-user unread count is cached, and only for a few seconds — enough to
// absorb badge-polling bursts without serving stale counts. Any mutation
// (mark-read / mark-all-read) invalidates the user's entry immediately, so the
// badge is never inconsistent.
package notificationbff

import (
	"sync"
	"time"
)

type unreadEntry struct {
	count     int64
	expiresAt time.Time
}

type UnreadCache struct {
	mu      sync.Mutex
	entries map[string]unreadEntry
	ttl     time.Duration
	maxSize int
	now     func() time.Time
}

func NewUnreadCache(ttl time.Duration, maxSize int) *UnreadCache {
	return &UnreadCache{entries: make(map[string]unreadEntry), ttl: ttl, maxSize: maxSize, now: time.Now}
}

func (c *UnreadCache) Get(userID string) (int64, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.entries[userID]
	if !ok || c.now().After(e.expiresAt) {
		if ok {
			delete(c.entries, userID)
		}
		return 0, false
	}
	return e.count, true
}

func (c *UnreadCache) Set(userID string, count int64) {
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
	c.entries[userID] = unreadEntry{count: count, expiresAt: c.now().Add(c.ttl)}
}

// Invalidate drops a user's cached count (after a mutation).
func (c *UnreadCache) Invalidate(userID string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.entries, userID)
}
