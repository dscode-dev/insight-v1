// Package redisstore implements Redis-backed adapters.
//
// `CooldownStore` is the per-phone OTP resend cooldown — the same
// rate-limit budget the legacy BFF enforced, on the same Redis key
// prefix so the two systems share state during the overlap.
//
// Package name is `redisstore` (not `redis`) to avoid clashing with
// the import alias of `github.com/redis/go-redis/v9` (its package is
// also `redis`).
package redisstore

import (
	"context"
	"errors"
	"time"

	"github.com/redis/go-redis/v9"
)

// CooldownStore — Redis store of "last OTP request timestamp per phone".
// Keys: `<KeyPrefix><phone_e164>` (string holding RFC3339 timestamp).
// TTL set to the cooldown window so expired entries auto-purge.
type CooldownStore struct {
	Client    *redis.Client
	KeyPrefix string // legacy key prefix kept for continuity of live cooldowns
}

func NewCooldownStore(client *redis.Client, keyPrefix string) *CooldownStore {
	if keyPrefix == "" {
		keyPrefix = "insight:atrium:otp_cooldown:"
	}
	return &CooldownStore{Client: client, KeyPrefix: keyPrefix}
}

func (s *CooldownStore) key(phoneE164 string) string {
	return s.KeyPrefix + phoneE164
}

// LastRequestAt returns the timestamp of the most recent successful
// OTP request for this phone, or zero time if no entry exists.
func (s *CooldownStore) LastRequestAt(ctx context.Context, phoneE164 string) (time.Time, error) {
	v, err := s.Client.Get(ctx, s.key(phoneE164)).Result()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			return time.Time{}, nil
		}
		return time.Time{}, err
	}
	t, err := time.Parse(time.RFC3339Nano, v)
	if err != nil {
		// Garbage value (perhaps from a different consumer that picked
		// the same key). Treat as no-entry rather than failing — worst
		// case we'd send one extra OTP, not the end of the world.
		return time.Time{}, nil
	}
	return t, nil
}

// MarkRequested writes `at` under the phone key with TTL = `ttl`.
// Idempotent — overwrites any existing value.
func (s *CooldownStore) MarkRequested(ctx context.Context, phoneE164 string, at time.Time, ttl time.Duration) error {
	return s.Client.Set(ctx, s.key(phoneE164), at.Format(time.RFC3339Nano), ttl).Err()
}
