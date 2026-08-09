package edgelimit

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func okHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
}

func get(path, ip string) *http.Request {
	r := httptest.NewRequest(http.MethodGet, path, nil)
	r.RemoteAddr = ip + ":54321"
	return r
}

func TestBurstIsAllowedThenRefused(t *testing.T) {
	l := New(Limits{Default: Config{Rate: 1, Burst: 3}})
	h := l.Middleware(okHandler())

	for i := 0; i < 3; i++ {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, get("/v1/feed", "10.0.0.1"))
		if rec.Code != http.StatusOK {
			t.Fatalf("request %d: code = %d, want 200", i+1, rec.Code)
		}
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/feed", "10.0.0.1"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("code = %d, want 429", rec.Code)
	}
	// A 429 with no Retry-After tells a client to guess, and clients guess
	// "immediately".
	if rec.Header().Get("Retry-After") == "" {
		t.Error("429 carries no Retry-After")
	}
}

func TestClientsAreLimitedIndependently(t *testing.T) {
	l := New(Limits{Default: Config{Rate: 1, Burst: 1}})
	h := l.Middleware(okHandler())

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/feed", "10.0.0.1"))
	if rec.Code != http.StatusOK {
		t.Fatalf("first client refused: %d", rec.Code)
	}
	// A second address must not inherit the first's exhausted bucket.
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/feed", "10.0.0.2"))
	if rec.Code != http.StatusOK {
		t.Fatalf("second client refused: %d", rec.Code)
	}
}

// The auth bucket is the whole reason this exists: the OTP endpoint costs a
// real SMS per call, and the per-phone cooldown does nothing against an
// attacker rotating numbers.
func TestAuthPathsUseTheStrictBucket(t *testing.T) {
	l := New(Limits{
		Auth:    Config{Rate: 0.1, Burst: 2},
		Default: Config{Rate: 100, Burst: 100},
	})
	h := l.Middleware(okHandler())

	for i := 0; i < 2; i++ {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, get("/v1/auth/phone/request", "10.0.0.9"))
		if rec.Code != http.StatusOK {
			t.Fatalf("auth request %d refused early: %d", i+1, rec.Code)
		}
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/auth/phone/request", "10.0.0.9"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("third auth request: code = %d, want 429", rec.Code)
	}

	// The same client is nowhere near the generous default bucket.
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/feed", "10.0.0.9"))
	if rec.Code != http.StatusOK {
		t.Fatalf("the strict auth bucket leaked into ordinary traffic: %d", rec.Code)
	}
}

func TestBucketRefillsOverTime(t *testing.T) {
	l := New(Limits{Default: Config{Rate: 10, Burst: 1}})
	now := time.Now()
	l.now = func() time.Time { return now }
	h := l.Middleware(okHandler())

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/feed", "10.0.0.3"))
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/feed", "10.0.0.3"))
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("bucket did not empty: %d", rec.Code)
	}

	now = now.Add(200 * time.Millisecond) // 10/s → 2 tokens
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/feed", "10.0.0.3"))
	if rec.Code != http.StatusOK {
		t.Fatalf("bucket did not refill: %d", rec.Code)
	}
}

// Throttling a liveness probe makes Kubernetes restart a pod for being busy,
// which is the opposite of what a limiter is for.
func TestProbesAreNeverLimited(t *testing.T) {
	l := New(Limits{Default: Config{Rate: 0.0001, Burst: 0}})
	h := l.Middleware(okHandler())

	for _, path := range []string{"/healthz", "/readyz", "/metrics"} {
		for i := 0; i < 20; i++ {
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, get(path, "10.0.0.4"))
			if rec.Code != http.StatusOK {
				t.Fatalf("%s throttled on request %d: %d", path, i+1, rec.Code)
			}
		}
	}
}

// Taking the FIRST X-Forwarded-For entry — the common shortcut — lets any
// caller pick their own bucket by sending the header. Only the last entry was
// written by the trusted proxy.
func TestSpoofedForwardedForCannotEscapeTheBucket(t *testing.T) {
	l := New(Limits{Default: Config{Rate: 0.001, Burst: 1}})
	h := l.Middleware(okHandler())

	first := httptest.NewRequest(http.MethodGet, "/v1/feed", nil)
	first.RemoteAddr = "10.0.0.5:1"
	first.Header.Set("X-Forwarded-For", "1.1.1.1, 203.0.113.7")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, first)
	if rec.Code != http.StatusOK {
		t.Fatalf("first request refused: %d", rec.Code)
	}

	// Same real client, different spoofed leading entry. If the limiter read
	// the first entry, this would be a fresh bucket and return 200.
	second := httptest.NewRequest(http.MethodGet, "/v1/feed", nil)
	second.RemoteAddr = "10.0.0.5:2"
	second.Header.Set("X-Forwarded-For", "2.2.2.2, 203.0.113.7")
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, second)
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("a spoofed X-Forwarded-For got a fresh bucket: %d", rec.Code)
	}
}

// Without eviction, one bucket per source address is an unbounded map an
// attacker fills for free.
func TestIdleBucketsAreEvicted(t *testing.T) {
	l := New(DefaultLimits())
	now := time.Now()
	l.now = func() time.Time { return now }
	h := l.Middleware(okHandler())

	for i := 0; i < 50; i++ {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, get("/v1/feed", fmt.Sprintf("10.1.0.%d", i)))
	}
	before := len(l.buckets)
	if before == 0 {
		t.Fatal("no buckets were created")
	}

	now = now.Add(11 * time.Minute)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, get("/v1/feed", "10.2.0.1"))

	if len(l.buckets) >= before {
		t.Fatalf("buckets = %d, expected the idle ones to be swept (was %d)",
			len(l.buckets), before)
	}
}
