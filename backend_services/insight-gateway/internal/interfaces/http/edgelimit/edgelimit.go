// Package edgelimit — per-client rate limiting at the Gateway edge.
//
//	insight-context.md v2.0 — Insight Gateway
//	Atuações: ... Rate Limiting ...
//
// It was a declared responsibility with no implementation at the edge. The
// global chain was Recovery → RequestID → BodyLimit → SecurityHeaders, and
// the only throttling in the service lived inside two BFF handlers
// (communitybff, searchbff) — so the endpoints nobody had thought to protect
// were the unprotected ones.
//
// WHAT THIS DOES AND DOES NOT REPLACE. The OTP flow already has a per-phone
// cooldown, which bounds SMS-bombing one victim's number. It does nothing
// against an attacker rotating numbers: each request is a first request for
// its phone, and each one costs a real SMS. That is SMS pumping, and it is
// billed to us. A per-IP limit is the control that bounds it, so the auth
// paths get a much tighter bucket than everything else.
//
// TOKEN BUCKET, NOT A FIXED WINDOW. A fixed window lets a client spend its
// whole allowance in the last instant of one window and again in the first
// instant of the next — twice the intended rate, at the worst possible
// moment. A bucket refills continuously and has no edge to sit on.
//
// IN-PROCESS, AND HONEST ABOUT IT. The counters live in this pod. With N
// replicas the effective limit is N times the configured one. That is a real
// limitation and the right trade for now: a shared Redis counter puts a
// network round-trip in front of every request, including the ones that are
// not close to the limit. The HPA caps replicas, so the multiplier is
// bounded and known rather than open-ended.
package edgelimit

import (
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Config describes one bucket class.
type Config struct {
	// Rate is sustained requests per second per client.
	Rate float64
	// Burst is how many requests a client may make back-to-back.
	Burst float64
}

// Limits holds the two classes the edge distinguishes.
type Limits struct {
	// Auth guards credential and OTP endpoints, where each request can cost
	// money (an SMS) or is an attempt at someone's account.
	Auth Config
	// Default guards everything else.
	Default Config
}

// DefaultLimits are deliberately generous for reads and strict for auth.
//
// A real client browsing a feed makes bursts of requests; a limit tight
// enough to stop scraping would also break the app. Auth is different: no
// legitimate client requests five OTPs a minute.
func DefaultLimits() Limits {
	return Limits{
		Auth:    Config{Rate: 0.1, Burst: 5},  // ~6/min, burst 5
		Default: Config{Rate: 20, Burst: 100}, // 20/s sustained
	}
}

type bucket struct {
	tokens float64
	last   time.Time
}

// Limiter is the middleware's state: one bucket per (class, client).
type Limiter struct {
	limits Limits
	now    func() time.Time

	mu      sync.Mutex
	buckets map[string]*bucket
	// lastSweep bounds memory: without eviction, one bucket per source
	// address is an unbounded map an attacker fills for free.
	lastSweep time.Time
}

func New(limits Limits) *Limiter {
	return &Limiter{
		limits:  limits,
		now:     time.Now,
		buckets: make(map[string]*bucket),
	}
}

// authPrefixes are the paths that get the strict bucket.
var authPrefixes = []string{
	"/v1/auth/",
	"/v1/operator/auth/",
}

func classOf(path string) (string, Config, bool) {
	for _, prefix := range authPrefixes {
		if strings.HasPrefix(path, prefix) {
			return "auth", Config{}, true
		}
	}
	return "default", Config{}, false
}

// Middleware returns the handler wrapper.
func (l *Limiter) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Health and metrics are never limited: throttling a liveness probe
		// makes Kubernetes restart a pod for being busy, which is the
		// opposite of what a limiter is for.
		if r.URL.Path == "/healthz" || r.URL.Path == "/readyz" || r.URL.Path == "/metrics" {
			next.ServeHTTP(w, r)
			return
		}

		class, _, isAuth := classOf(r.URL.Path)
		cfg := l.limits.Default
		if isAuth {
			cfg = l.limits.Auth
		}

		key := class + "|" + clientIP(r)
		if allowed, retryAfter := l.allow(key, cfg); !allowed {
			w.Header().Set("Retry-After", strconv.Itoa(int(retryAfter.Seconds())+1))
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusTooManyRequests)
			_, _ = w.Write([]byte(`{"detail":"rate_limited"}`))
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (l *Limiter) allow(key string, cfg Config) (bool, time.Duration) {
	now := l.now()
	l.mu.Lock()
	defer l.mu.Unlock()

	l.sweepLocked(now)

	b, ok := l.buckets[key]
	if !ok {
		b = &bucket{tokens: cfg.Burst, last: now}
		l.buckets[key] = b
	}
	// Refill for elapsed time, capped at burst.
	elapsed := now.Sub(b.last).Seconds()
	if elapsed > 0 {
		b.tokens += elapsed * cfg.Rate
		if b.tokens > cfg.Burst {
			b.tokens = cfg.Burst
		}
		b.last = now
	}
	if b.tokens < 1 {
		// How long until one token is available.
		need := (1 - b.tokens) / cfg.Rate
		return false, time.Duration(need * float64(time.Second))
	}
	b.tokens--
	return true, 0
}

// sweepLocked drops buckets that have been full (idle) long enough that
// forgetting them changes nothing.
func (l *Limiter) sweepLocked(now time.Time) {
	if now.Sub(l.lastSweep) < time.Minute {
		return
	}
	l.lastSweep = now
	for key, b := range l.buckets {
		if now.Sub(b.last) > 10*time.Minute {
			delete(l.buckets, key)
		}
	}
}

// clientIP resolves the caller's address.
//
// X-Forwarded-For is read ONLY as the ingress writes it — the LAST entry is
// the one the trusted proxy appended, and the earlier ones are whatever the
// client sent. Taking the first, which is the common shortcut, lets any
// caller choose their own rate-limit bucket by sending a header.
func clientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		parts := strings.Split(xff, ",")
		last := strings.TrimSpace(parts[len(parts)-1])
		if last != "" {
			return last
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
