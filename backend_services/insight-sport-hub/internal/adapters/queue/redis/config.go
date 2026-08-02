// Package redis — Sprint 4 Redis Streams adapter satisfying
// ports.JobQueue.
//
// Architectural rule: this is the ONLY package allowed to import
// `github.com/redis/go-redis/v9`. The application layer + every
// other adapter goes through `ports.JobQueue`. Boundary tests in
// tests/application/scheduler_boundary_test.go parse the import
// graph + fail if scheduler/jobrunner/ratelimit leak a Redis import.
package redis

import (
	"errors"
	"time"
)

// Config — wire shape from the composition root.
type Config struct {
	// Addr is the Redis endpoint, "host:port".
	Addr string

	// Password is optional. Never logged.
	Password string

	// DB selects the logical Redis database (default 0).
	DB int

	// Stream is the Redis stream key SyncJobs are XADDed to.
	// Convention: "insight:queue:syncjobs".
	Stream string

	// Group is the consumer group every worker joins. Single group
	// for Sprint 4 ("Do NOT implement multiple consumer groups yet").
	Group string

	// ConsumerName is the unique name of THIS process within the
	// group. Conventionally hostname + pid; main.go fills it.
	ConsumerName string

	// MaxLen caps the stream length via XADD MAXLEN ~ N. Older
	// entries are trimmed when the cap is exceeded. Approximate
	// trimming (~) is cheaper than exact and acceptable for our
	// purposes.
	MaxLen int64

	// RetryZSet — sorted set storing jobs whose RetryAfter has not
	// yet elapsed. Score == unix-nano of RetryAfter. A small promoter
	// goroutine polls + XADDs ready entries back to the stream.
	RetryZSet string

	// BlockTimeout for XREADGROUP. Longer = fewer round trips at
	// idle; shorter = faster ctx cancel observability. 5s is a good
	// default.
	BlockTimeout time.Duration

	// PromoterInterval — how often the retry promoter scans the
	// RetryZSet. 1s for tight cadences, 5s for relaxed lab use.
	PromoterInterval time.Duration

	// DialTimeout — connection establishment cap. Connect failures
	// surface from NewQueue as boot errors.
	DialTimeout time.Duration

	// Sprint 5.1 — pending-message claimer (Part 6). Zero value
	// disables the claimer (Sprint 4 behaviour); set Enabled=true to
	// start the background goroutine.
	Claimer ClaimerConfig
}

// Defaults applies safe defaults to any zero-valued field. Returns
// the same config for chaining.
func (c Config) Defaults() Config {
	if c.Stream == "" {
		c.Stream = "insight:queue:syncjobs"
	}
	if c.Group == "" {
		c.Group = "insight-syncjob-workers"
	}
	if c.RetryZSet == "" {
		c.RetryZSet = "insight:queue:syncjobs:retry"
	}
	if c.MaxLen <= 0 {
		c.MaxLen = 10_000
	}
	if c.BlockTimeout <= 0 {
		c.BlockTimeout = 5 * time.Second
	}
	if c.PromoterInterval <= 0 {
		c.PromoterInterval = 1 * time.Second
	}
	if c.DialTimeout <= 0 {
		c.DialTimeout = 5 * time.Second
	}
	return c
}

// Validate checks the required-at-boot fields. Addr + ConsumerName
// are caller responsibility.
func (c Config) Validate() error {
	if c.Addr == "" {
		return errors.New("redis queue: Addr required")
	}
	if c.ConsumerName == "" {
		return errors.New("redis queue: ConsumerName required")
	}
	return nil
}
