// Package redisinfra — Sprint 6.1 Redis-backed odds infrastructure.
//
// Production implementations of the small store/cache/source seams the
// odds pipeline defines in the application + provider layers:
//
//   - OddsResponseCache → the_odds_api.ResponseCache  (quota-saving cache)
//   - BudgetStore       → budget.CounterStore         (long-window quotas)
//   - LastOddsStore     → oddschange.LastOddsStore     (change detection)
//   - ModeSource        → oddsmode.Source              (runtime mode flag)
//
// These are the ONLY odds components that touch Redis directly — kept
// in one infrastructure adapter package so the import-boundary test has
// a single approved location to allowlist. All impls share one
// *redis.Client constructed by the composition root.
package redisinfra

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"golang.org/x/sync/singleflight"

	"github.com/konoha-labs/insight-sports-hub/internal/application/oddsmode"
)

// Config tunes the Redis-backed odds stores.
type Config struct {
	CacheTTL    time.Duration // odds response cache TTL
	CachePrefix string
	LastPrefix  string // last-published odds key prefix
	ModeKey     string // runtime ODDS_MODE key
}

// NewClient builds + pings a Redis client for the odds infra stores.
// The composition root owns the lifecycle (Close on shutdown).
func NewClient(ctx context.Context, addr, password string, db int, dialTimeout time.Duration) (*goredis.Client, error) {
	if dialTimeout <= 0 {
		dialTimeout = 5 * time.Second
	}
	client := goredis.NewClient(&goredis.Options{
		Addr:        addr,
		Password:    password,
		DB:          db,
		DialTimeout: dialTimeout,
	})
	if err := client.Ping(ctx).Err(); err != nil {
		_ = client.Close()
		return nil, fmt.Errorf("redisinfra: ping: %w", err)
	}
	return client, nil
}

// Defaults fills sensible defaults.
func (c Config) Defaults() Config {
	if c.CacheTTL <= 0 {
		c.CacheTTL = 60 * time.Second
	}
	if c.CachePrefix == "" {
		c.CachePrefix = "insight:odds:cache:"
	}
	if c.LastPrefix == "" {
		c.LastPrefix = "insight:odds:last:"
	}
	if c.ModeKey == "" {
		c.ModeKey = "insight:odds:mode"
	}
	return c
}

// ---- odds response cache (with request collapsing) ----

// OddsResponseCache caches marshaled provider responses in Redis and
// collapses concurrent identical fetches via singleflight, so a burst
// of scheduler lanes hitting the same sport_key spends one API call.
type OddsResponseCache struct {
	client *goredis.Client
	ttl    time.Duration
	prefix string
	group  singleflight.Group
}

func NewOddsResponseCache(client *goredis.Client, ttl time.Duration, prefix string) *OddsResponseCache {
	return &OddsResponseCache{client: client, ttl: ttl, prefix: prefix}
}

// Fetch satisfies the_odds_api.ResponseCache.
func (c *OddsResponseCache) Fetch(
	ctx context.Context, key string, loader func(context.Context) ([]byte, error),
) ([]byte, error) {
	full := c.prefix + key
	if b, err := c.client.Get(ctx, full).Bytes(); err == nil {
		return b, nil
	} else if err != goredis.Nil {
		// Redis read error — fall through to loader (fail open).
		_ = err
	}

	v, err, _ := c.group.Do(key, func() (interface{}, error) {
		// Double-check inside the flight: a concurrent leader may have
		// just populated the cache.
		if b, gerr := c.client.Get(ctx, full).Bytes(); gerr == nil {
			return b, nil
		}
		b, lerr := loader(ctx)
		if lerr != nil {
			return nil, lerr
		}
		if serr := c.client.Set(ctx, full, b, c.ttl).Err(); serr != nil {
			// Caching failure is non-fatal — return the fresh bytes.
			return b, nil
		}
		return b, nil
	})
	if err != nil {
		return nil, err
	}
	return v.([]byte), nil
}

// ---- budget counter store ----

// BudgetStore satisfies budget.CounterStore using Redis INCR + EXPIRE.
type BudgetStore struct {
	client *goredis.Client
}

func NewBudgetStore(client *goredis.Client) *BudgetStore {
	return &BudgetStore{client: client}
}

func (s *BudgetStore) Increment(ctx context.Context, key string, ttl time.Duration) (int64, error) {
	n, err := s.client.Incr(ctx, key).Result()
	if err != nil {
		return 0, fmt.Errorf("redisinfra: budget incr: %w", err)
	}
	if n == 1 && ttl > 0 {
		// First write in this window — pin the TTL so the counter
		// self-expires when the window rolls over.
		_ = s.client.Expire(ctx, key, ttl).Err()
	}
	return n, nil
}

func (s *BudgetStore) Count(ctx context.Context, key string) (int64, error) {
	n, err := s.client.Get(ctx, key).Int64()
	if err == goredis.Nil {
		return 0, nil
	}
	if err != nil {
		return 0, fmt.Errorf("redisinfra: budget get: %w", err)
	}
	return n, nil
}

// ---- last-published odds store (change detection) ----

// LastOddsStore satisfies oddschange.LastOddsStore.
type LastOddsStore struct {
	client *goredis.Client
	prefix string
}

func NewLastOddsStore(client *goredis.Client, prefix string) *LastOddsStore {
	return &LastOddsStore{client: client, prefix: prefix}
}

func (s *LastOddsStore) Get(ctx context.Context, key string) (map[string]float64, bool, error) {
	raw, err := s.client.Get(ctx, s.prefix+key).Bytes()
	if err == goredis.Nil {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("redisinfra: last odds get: %w", err)
	}
	var out map[string]float64
	if uerr := json.Unmarshal(raw, &out); uerr != nil {
		return nil, false, fmt.Errorf("redisinfra: last odds decode: %w", uerr)
	}
	return out, true, nil
}

func (s *LastOddsStore) Put(ctx context.Context, key string, prices map[string]float64, ttl time.Duration) error {
	raw, err := json.Marshal(prices)
	if err != nil {
		return fmt.Errorf("redisinfra: last odds encode: %w", err)
	}
	if serr := s.client.Set(ctx, s.prefix+key, raw, ttl).Err(); serr != nil {
		return fmt.Errorf("redisinfra: last odds set: %w", serr)
	}
	return nil
}

// ---- operational mode source ----

// ModeSource satisfies oddsmode.Source by reading a single Redis key an
// operator flips at runtime (SET insight:odds:mode worldcup).
type ModeSource struct {
	client *goredis.Client
	key    string
}

func NewModeSource(client *goredis.Client, key string) *ModeSource {
	return &ModeSource{client: client, key: key}
}

func (m *ModeSource) Mode(ctx context.Context) (oddsmode.Mode, error) {
	v, err := m.client.Get(ctx, m.key).Result()
	if err == goredis.Nil {
		return oddsmode.ModeNormal, nil
	}
	if err != nil {
		return oddsmode.ModeNormal, fmt.Errorf("redisinfra: mode get: %w", err)
	}
	return oddsmode.Parse(v), nil
}
