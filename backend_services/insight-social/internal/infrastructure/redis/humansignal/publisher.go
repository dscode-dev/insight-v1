// Package humansignal is the Redis Streams implementation of
// domain/signal.Publisher.
//
// Partitioning: stream key = `<prefix>:<partition>` where partition
// is `crc32(author_id) % StreamPartitions`. This matches the layout
// the insight-gateway broker reads from (8 partitions by default) so
// SSE fan-out works without any extra coordination.
//
// Maxlen: streams are capped at `MAXLEN ~ <maxLen>` (approximate
// trim) so a runaway producer doesn't blow up Redis memory. Default
// 100k per partition — enough headroom for ~14 days of normal
// activity even on a single big match.
//
// Idempotency: NOT enforced here. The Stream entry carries the
// `signal_id` (DB primary key) — consumers dedupe by that key using
// SET-NX. See insight-gateway/internal/realtime/broker.go.
package humansignal

import (
	"context"
	"fmt"
	"hash/crc32"
	"strconv"

	"github.com/redis/go-redis/v9"

	domsignal "github.com/konoha-labs/insight-social/internal/domain/signal"
)

// Config carries the knobs settable from main.go via Settings.
type Config struct {
	Client     *redis.Client
	KeyPrefix  string // e.g. "insight:stream:human_signal"
	Partitions int    // 8 by default; MUST match the gateway broker
	MaxLen     int64  // approximate cap per partition; 0 disables trim
}

type Publisher struct {
	cfg Config
}

func New(cfg Config) (*Publisher, error) {
	if cfg.Client == nil {
		return nil, fmt.Errorf("humansignal: redis client required")
	}
	if cfg.Partitions <= 0 {
		return nil, fmt.Errorf("humansignal: partitions must be > 0 (got %d)", cfg.Partitions)
	}
	if cfg.KeyPrefix == "" {
		return nil, fmt.Errorf("humansignal: key prefix required")
	}
	if cfg.MaxLen == 0 {
		cfg.MaxLen = 100_000
	}
	return &Publisher{cfg: cfg}, nil
}

func (p *Publisher) Publish(ctx context.Context, s *domsignal.Signal) error {
	key := p.streamKey(s.AuthorID().String())

	args := &redis.XAddArgs{
		Stream: key,
		MaxLen: p.cfg.MaxLen,
		Approx: true, // MAXLEN ~ (cheaper trim, slop a few hundred entries)
		Values: map[string]any{
			"signal_id":  strconv.FormatInt(s.ID(), 10),
			"author_id":  s.AuthorID().String(),
			"match_id":   s.MatchID().String(),
			"source":     s.Source().String(),
			"label":      s.Label(),
			"body":       s.Body(),
			"confidence": strconv.FormatFloat(s.Confidence(), 'f', -1, 64),
			"state":      s.State().String(),
			"ts":         s.Ts().UTC().Format("2006-01-02T15:04:05.000000000Z07:00"),
		},
	}
	if _, err := p.cfg.Client.XAdd(ctx, args).Result(); err != nil {
		return fmt.Errorf("xadd %s: %w", key, err)
	}
	return nil
}

// streamKey: same hash bucket the gateway broker uses. crc32 is
// fast and the distribution quality is fine for 8-way partitioning.
func (p *Publisher) streamKey(authorID string) string {
	partition := int(crc32.ChecksumIEEE([]byte(authorID))) % p.cfg.Partitions
	if partition < 0 {
		partition = -partition
	}
	return fmt.Sprintf("%s:%d", p.cfg.KeyPrefix, partition)
}
