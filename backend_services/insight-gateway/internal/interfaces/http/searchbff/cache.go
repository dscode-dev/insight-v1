// Per-user response cache. The key covers EVERY request dimension —
// user | category | query | cursor | limit — so no entry is ever shared
// between users (a user's mutual/follow flags and moderation lens make results
// viewer-specific) and pagination pages never collide.
//
// In-memory + TTL: the gateway runs single-instance in the current topology;
// the interface is deliberately small so a Redis-backed impl can swap in
// without touching handlers. Bounded: expired entries are swept on write; when
// still full, new entries are simply not cached (never evict live entries
// unpredictably — determinism over hit-rate).

package searchbff

import (
	"crypto/sha256"
	"encoding/hex"
	"strconv"
	"sync"
	"time"
)

type cacheEntry struct {
	body      []byte
	expiresAt time.Time
}

type Cache struct {
	mu      sync.Mutex
	entries map[string]cacheEntry
	ttl     time.Duration
	maxSize int
	now     func() time.Time
}

func NewCache(ttl time.Duration, maxSize int) *Cache {
	return &Cache{
		entries: make(map[string]cacheEntry),
		ttl:     ttl,
		maxSize: maxSize,
		now:     time.Now,
	}
}

// Key builds the full-dimension cache key (hashed: user ids and queries never
// sit as plaintext map keys in memory profiles/logs).
func (c *Cache) Key(userID, category, query, cursor string, limit int) string {
	h := sha256.Sum256([]byte(userID + "\x1f" + category + "\x1f" + query +
		"\x1f" + cursor + "\x1f" + strconv.Itoa(limit)))
	return hex.EncodeToString(h[:])
}

func (c *Cache) Get(key string) ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.entries[key]
	if !ok || c.now().After(e.expiresAt) {
		if ok {
			delete(c.entries, key)
		}
		return nil, false
	}
	return e.body, true
}

func (c *Cache) Set(key string, body []byte) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.entries) >= c.maxSize {
		now := c.now()
		for k, e := range c.entries { // sweep expired
			if now.After(e.expiresAt) {
				delete(c.entries, k)
			}
		}
		if len(c.entries) >= c.maxSize {
			return // full of LIVE entries: skip caching rather than evict unpredictably
		}
	}
	c.entries[key] = cacheEntry{body: body, expiresAt: c.now().Add(c.ttl)}
}
