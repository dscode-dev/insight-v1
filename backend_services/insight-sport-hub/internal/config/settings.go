// Package config — typed Settings + env parser.
//
// Sprint 1 scope: only the boot knobs the foundation needs
// (Postgres, HTTP listener, future-skew tolerance, observability).
// Sprint 2 adds publisher knobs (Redis Streams target) once the
// real adapter ships.
package config

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	rtconfig "github.com/konoha-labs/insight-runtime-go/pkg/config"
)

type Settings struct {
	Service string
	Version string

	HTTPAddr string
	OpsToken string

	DatabaseURL         string
	DatabasePoolSize    int
	DatabaseMaxOverflow int

	// Validation tunables.
	FutureSkew time.Duration

	// Sprint 2 — provider adapter knobs.
	// Each adapter is built ONLY when its API key is present; empty
	// keys skip the adapter (logged warn) so local-lab boots without
	// holding production credentials. BaseURL is optional —
	// defaults to the provider's production host when empty.
	APIFootballKey      string
	APIFootballBaseURL  string
	FootballDataKey     string
	FootballDataBaseURL string
	TheOddsAPIKey       string
	TheOddsAPIBaseURL   string

	// Sprint 3 — scheduler / runner / queue.
	SchedulerInterval      time.Duration
	SchedulerQueueCapacity int
	JobRunnerWorkers       int

	// Sprint 4 — distributed queue.
	// QueueBackend selects the JobQueue impl: "inmemory" (Sprint 3
	// default, lab/dev) or "redis" (Sprint 4 production).
	QueueBackend   string
	RedisAddr      string
	RedisPassword  string
	RedisDB        int
	RedisStream    string
	RedisGroup     string
	RedisConsumer  string
	RedisRetryZSet string
	RedisMaxLen    int64

	// Sprint 5 — canonical-event publisher backend selection.
	// "noop" (default, lab) or "redis" (production — Atlas + Anvil
	// consume).
	PublisherBackend     string
	PublisherStreamMatch string
	PublisherStreamOdds  string
	PublisherStreamCtx   string
	PublisherMaxLen      int64

	// Sprint 5.1 — pending-message claimer (Part 6).
	ClaimerEnabled        bool
	ClaimerMinIdleSeconds int
	ClaimerIntervalSec    int
	ClaimerMaxDeliveries  int

	// Sprint 6.1 — odds production hardening.
	OddsChangeThresholdPercent float64       // publish gate; 0 disables denoising
	OddsCacheTTL               time.Duration // response cache TTL
	OddsBudgetMonthly          int           // 0 = no cap
	OddsBudgetDaily            int
	OddsBudgetHourly           int
	OddsMode                   string        // "normal" | "worldcup" (boot default)
	OddsModeCacheTTL           time.Duration // how often the mode flag is re-read
	OddsWorldCupPollMultiplier float64       // <1 polls more often in worldcup mode
	// Dynamic polling reference windows (kickoff proximity → cadence).
	OddsPollLive      time.Duration // in-play
	OddsPollWindow6h  time.Duration // kickoff < 6h
	OddsPollWindow48h time.Duration // kickoff < 48h
	OddsPollWindow7d  time.Duration // kickoff < 7d
	OddsPollDefault   time.Duration // farther than 7d / unknown

	// Sprint 6.2 — cross-provider match identity kickoff tolerance.
	IdentityKickoffTolerance time.Duration

	// Observability.
	LogLevel        string
	LogPretty       bool
	OTLPEndpoint    string
	OTLPSampleRatio float64
}

func Load() (*Settings, error) {
	s := &Settings{
		Service:     rtconfig.String("INSIGHT_SERVICE", "insight-sports-hub"),
		Version:     rtconfig.String("INSIGHT_VERSION", "dev"),
		HTTPAddr:    rtconfig.String("HTTP_ADDR", ":8080"),
		OpsToken:    rtconfig.String("SPORT_HUB_OPS_TOKEN", ""),
		DatabaseURL: rtconfig.MustString("DATABASE_URL"),

		// Provider adapter env. Empty key → skipped at boot.
		APIFootballKey:      rtconfig.String("API_FOOTBALL_KEY", ""),
		APIFootballBaseURL:  rtconfig.String("API_FOOTBALL_BASE_URL", ""),
		FootballDataKey:     rtconfig.String("FOOTBALL_DATA_KEY", ""),
		FootballDataBaseURL: rtconfig.String("FOOTBALL_DATA_BASE_URL", ""),
		TheOddsAPIKey:       rtconfig.String("THE_ODDS_API_KEY", ""),
		TheOddsAPIBaseURL:   rtconfig.String("THE_ODDS_API_BASE_URL", ""),

		LogLevel:     rtconfig.String("LOG_LEVEL", "info"),
		LogPretty:    rtconfig.Bool("LOG_PRETTY", false),
		OTLPEndpoint: rtconfig.String("INSIGHT_OTLP_ENDPOINT", ""),
	}
	var err error
	if s.DatabasePoolSize, err = rtconfig.Int("DATABASE_POOL_SIZE", 10); err != nil {
		return nil, fmt.Errorf("DATABASE_POOL_SIZE: %w", err)
	}
	if s.DatabaseMaxOverflow, err = rtconfig.Int("DATABASE_MAX_OVERFLOW", 20); err != nil {
		return nil, fmt.Errorf("DATABASE_MAX_OVERFLOW: %w", err)
	}
	skewSecs, err := rtconfig.Int("VALIDATION_FUTURE_SKEW_SECONDS", 300)
	if err != nil {
		return nil, fmt.Errorf("VALIDATION_FUTURE_SKEW_SECONDS: %w", err)
	}
	s.FutureSkew = time.Duration(skewSecs) * time.Second

	if s.OTLPSampleRatio, err = rtconfig.Float("INSIGHT_OTLP_SAMPLE_RATIO", 1.0); err != nil {
		return nil, fmt.Errorf("INSIGHT_OTLP_SAMPLE_RATIO: %w", err)
	}

	// Sprint 3 — scheduler/runner/queue knobs.
	intervalSecs, err := rtconfig.Int("SCHEDULER_INTERVAL_SECONDS", 30)
	if err != nil {
		return nil, fmt.Errorf("SCHEDULER_INTERVAL_SECONDS: %w", err)
	}
	s.SchedulerInterval = time.Duration(intervalSecs) * time.Second
	if s.SchedulerQueueCapacity, err = rtconfig.Int("SCHEDULER_QUEUE_CAPACITY", 1024); err != nil {
		return nil, fmt.Errorf("SCHEDULER_QUEUE_CAPACITY: %w", err)
	}
	if s.JobRunnerWorkers, err = rtconfig.Int("JOB_RUNNER_WORKERS", 4); err != nil {
		return nil, fmt.Errorf("JOB_RUNNER_WORKERS: %w", err)
	}

	// Sprint 4 — queue backend selection.
	// Supports both:
	//
	//   REDIS_URL=redis://host:6379/0
	//
	// and the legacy form:
	//
	//   REDIS_ADDR=host:6379
	//   REDIS_PASSWORD=
	//   REDIS_DB=0
	//
	// REDIS_URL takes precedence when present.
	s.QueueBackend = rtconfig.String("QUEUE_BACKEND", "inmemory")

	if redisURL := rtconfig.String("REDIS_URL", ""); redisURL != "" {
		addr, password, db, perr := parseRedisURL(redisURL)
		if perr != nil {
			return nil, fmt.Errorf("REDIS_URL: %w", perr)
		}
		s.RedisAddr = addr
		s.RedisPassword = password
		s.RedisDB = db
	} else {
		s.RedisAddr = rtconfig.String("REDIS_ADDR", "localhost:6379")
		s.RedisPassword = rtconfig.String("REDIS_PASSWORD", "")

		if s.RedisDB, err = rtconfig.Int("REDIS_DB", 0); err != nil {
			return nil, fmt.Errorf("REDIS_DB: %w", err)
		}
	}

	s.RedisStream = rtconfig.String("REDIS_STREAM", "insight:queue:syncjobs")
	s.RedisGroup = rtconfig.String("REDIS_GROUP", "insight-syncjob-workers")
	s.RedisConsumer = rtconfig.String("REDIS_CONSUMER", "")
	s.RedisRetryZSet = rtconfig.String("REDIS_RETRY_ZSET", "insight:queue:syncjobs:retry")

	maxLen64, err := rtconfig.Int("REDIS_MAX_LEN", 10000)
	if err != nil {
		return nil, fmt.Errorf("REDIS_MAX_LEN: %w", err)
	}
	s.RedisMaxLen = int64(maxLen64)

	// Sprint 5 — publisher backend selection.
	s.PublisherBackend = rtconfig.String("PUBLISHER_BACKEND", "noop")
	s.PublisherStreamMatch = rtconfig.String("PUBLISHER_STREAM_MATCH", "insight:stream:events:match")
	s.PublisherStreamOdds = rtconfig.String("PUBLISHER_STREAM_ODDS", "insight:stream:events:odds")
	s.PublisherStreamCtx = rtconfig.String("PUBLISHER_STREAM_CONTEXT", "insight:stream:events:context")
	pubMaxLen, err := rtconfig.Int("PUBLISHER_MAX_LEN", 100000)
	if err != nil {
		return nil, fmt.Errorf("PUBLISHER_MAX_LEN: %w", err)
	}
	s.PublisherMaxLen = int64(pubMaxLen)

	// Sprint 5.1 — Pending-message claimer (XCLAIM worker).
	s.ClaimerEnabled = rtconfig.Bool("CLAIMER_ENABLED", true)
	if s.ClaimerMinIdleSeconds, err = rtconfig.Int("CLAIMER_MIN_IDLE_SECONDS", 30); err != nil {
		return nil, fmt.Errorf("CLAIMER_MIN_IDLE_SECONDS: %w", err)
	}
	if s.ClaimerIntervalSec, err = rtconfig.Int("CLAIMER_INTERVAL_SECONDS", 5); err != nil {
		return nil, fmt.Errorf("CLAIMER_INTERVAL_SECONDS: %w", err)
	}
	if s.ClaimerMaxDeliveries, err = rtconfig.Int("CLAIMER_MAX_DELIVERIES", 8); err != nil {
		return nil, fmt.Errorf("CLAIMER_MAX_DELIVERIES: %w", err)
	}

	// Sprint 6.1 — odds hardening knobs.
	if s.OddsChangeThresholdPercent, err = rtconfig.Float("ODDS_CHANGE_THRESHOLD_PERCENT", 0.5); err != nil {
		return nil, fmt.Errorf("ODDS_CHANGE_THRESHOLD_PERCENT: %w", err)
	}
	if s.OddsCacheTTL, err = durationFromSeconds("ODDS_CACHE_TTL_SECONDS", 60); err != nil {
		return nil, err
	}
	if s.OddsBudgetMonthly, err = rtconfig.Int("ODDS_BUDGET_MONTHLY", 500); err != nil {
		return nil, fmt.Errorf("ODDS_BUDGET_MONTHLY: %w", err)
	}
	if s.OddsBudgetDaily, err = rtconfig.Int("ODDS_BUDGET_DAILY", 0); err != nil {
		return nil, fmt.Errorf("ODDS_BUDGET_DAILY: %w", err)
	}
	if s.OddsBudgetHourly, err = rtconfig.Int("ODDS_BUDGET_HOURLY", 0); err != nil {
		return nil, fmt.Errorf("ODDS_BUDGET_HOURLY: %w", err)
	}
	s.OddsMode = rtconfig.String("ODDS_MODE", "normal")
	if s.OddsModeCacheTTL, err = durationFromSeconds("ODDS_MODE_CACHE_TTL_SECONDS", 10); err != nil {
		return nil, err
	}
	if s.OddsWorldCupPollMultiplier, err = rtconfig.Float("ODDS_WORLDCUP_POLL_MULTIPLIER", 0.5); err != nil {
		return nil, fmt.Errorf("ODDS_WORLDCUP_POLL_MULTIPLIER: %w", err)
	}
	if s.OddsPollLive, err = durationFromSeconds("ODDS_POLL_LIVE_SECONDS", 60); err != nil {
		return nil, err
	}
	if s.OddsPollWindow6h, err = durationFromSeconds("ODDS_POLL_6H_SECONDS", 900); err != nil {
		return nil, err
	}
	if s.OddsPollWindow48h, err = durationFromSeconds("ODDS_POLL_48H_SECONDS", 3600); err != nil {
		return nil, err
	}
	if s.OddsPollWindow7d, err = durationFromSeconds("ODDS_POLL_7D_SECONDS", 6*3600); err != nil {
		return nil, err
	}
	if s.OddsPollDefault, err = durationFromSeconds("ODDS_POLL_DEFAULT_SECONDS", 12*3600); err != nil {
		return nil, err
	}

	// Sprint 6.2 — match identity kickoff tolerance (default 90 min).
	if s.IdentityKickoffTolerance, err = durationFromSeconds("IDENTITY_KICKOFF_TOLERANCE_SECONDS", 90*60); err != nil {
		return nil, err
	}

	return s, nil
}

// durationFromSeconds reads an integer-seconds env into a Duration.
func durationFromSeconds(key string, def int) (time.Duration, error) {
	secs, err := rtconfig.Int(key, def)
	if err != nil {
		return 0, fmt.Errorf("%s: %w", key, err)
	}
	return time.Duration(secs) * time.Second, nil
}

// parseRedisURL extracts the address, password, and DB index from a
// redis:// or rediss:// connection URL.
//
// Kept dependency-free (net/url + strconv) on purpose: the
// architectural boundary test forbids importing the go-redis client
// outside the queue/redis + publishing adapters, and config must stay
// on the right side of that line. Behaviour matches go-redis'
// ParseURL for the fields the Hub consumes:
//
//	redis://:password@host:6379/2  →  addr=host:6379 password=password db=2
//
// A missing port defaults to 6379; a missing/empty path defaults to DB 0.
func parseRedisURL(raw string) (addr, password string, db int, err error) {
	u, err := url.Parse(raw)
	if err != nil {
		return "", "", 0, err
	}
	if u.Scheme != "redis" && u.Scheme != "rediss" {
		return "", "", 0, fmt.Errorf("unsupported scheme %q", u.Scheme)
	}

	host := u.Hostname()
	if host == "" {
		return "", "", 0, fmt.Errorf("missing host")
	}
	port := u.Port()
	if port == "" {
		port = "6379"
	}
	addr = host + ":" + port

	if u.User != nil {
		password, _ = u.User.Password()
	}

	if p := strings.TrimPrefix(u.Path, "/"); p != "" {
		db, err = strconv.Atoi(p)
		if err != nil {
			return "", "", 0, fmt.Errorf("invalid db %q: %w", p, err)
		}
	}
	return addr, password, db, nil
}
