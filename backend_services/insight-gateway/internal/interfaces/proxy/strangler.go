// Package proxy is the Gateway's router core.
//
// Born as the Strangler for the legacy-BFF migration: native Go
// handlers registered on a chi.Mux in front of a reverse-proxy
// fallback, with per-endpoint rollout flags. The migration is
// complete — the platform default is STANDALONE mode (no upstream):
//
//	               ┌──────────────────────────┐
//	request ─────▶│ chi router               │
//	               │  ├─ /v1/auth/...   GO    │
//	               │  ├─ /v1/feed       GO    │
//	               │  ├─ /healthz       GO    │
//	               │  └─ NotFound → 404       │
//	               └──────────────────────────┘
//
// When an upstream URL is still configured (legacy overlap only), the
// original Strangler behaviour applies: unmatched routes and
// flagged-off routes proxy to the upstream. With no upstream, every
// registered route is served natively and everything else is 404.
package proxy

import (
	"bytes"
	"io"
	"math/rand"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/rs/zerolog"
)

// Strangler is the Gateway's top-level http.Handler. Embed it on the
// server struct and pass it to http.Server.
type Strangler struct {
	router        *chi.Mux
	upstreamURL   *url.URL
	upstreamProxy *httputil.ReverseProxy
}

// New constructs the Gateway router. With an empty `upstreamBaseURL`
// it runs STANDALONE: native routes only, unmatched requests get 404.
// With a URL it behaves as the legacy Strangler (unmatched → proxy).
// Returns an error when the URL is malformed — failing fast at boot
// is preferable to a confusing 502 in prod.
func New(upstreamBaseURL string) (*Strangler, error) {
	if strings.TrimSpace(upstreamBaseURL) == "" {
		router := chi.NewRouter()
		router.NotFound(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte(`{"error":"not_found"}`))
		})
		return &Strangler{router: router}, nil
	}

	u, err := url.Parse(strings.TrimRight(upstreamBaseURL, "/"))
	if err != nil {
		return nil, err
	}
	rp := httputil.NewSingleHostReverseProxy(u)

	// Preserve original Host header on the upstream — legacy BFFs use
	// it for absolute URL construction in SSE keepalives. The default
	// behaviour rewrites Host to the upstream's, which is wrong here.
	originalDirector := rp.Director
	rp.Director = func(r *http.Request) {
		originalDirector(r)
		// upstream sees `Host: <legacy service DNS>` but learns
		// the original through X-Forwarded-Host.
		if r.Header.Get("X-Forwarded-Host") == "" {
			r.Header.Set("X-Forwarded-Host", r.Host)
		}
		r.Header.Set("X-Forwarded-Proto", "http")
	}

	// SSE-friendly transport: no buffering, generous read timeouts.
	// The default RoundTripper is fine, but we explicitly opt out of
	// response buffering so long-lived event streams flush per chunk.
	rp.ModifyResponse = func(resp *http.Response) error {
		if strings.HasPrefix(resp.Header.Get("Content-Type"), "text/event-stream") {
			// Make sure the upstream's `X-Accel-Buffering: no` survives.
			resp.Header.Set("X-Accel-Buffering", "no")
		}
		return nil
	}

	router := chi.NewRouter()
	router.NotFound(func(w http.ResponseWriter, r *http.Request) {
		rp.ServeHTTP(w, r)
	})

	return &Strangler{
		router:        router,
		upstreamURL:   u,
		upstreamProxy: rp,
	}, nil
}

// Native registers a Go-side handler at the chi pattern with no flag
// gating — calls go straight to the handler, bypassing the proxy.
// Use for endpoints owned end-to-end by the gateway from day 1
// (/healthz, /readyz, /metrics).
//
// `pattern` follows chi conventions ("/v1/auth/otp/request",
// "/v1/live/matches/{id}").
func (s *Strangler) Native(method, pattern string, h http.Handler) {
	s.router.Method(method, pattern, h)
}

// NativeFlagged registers a Go handler that obeys a rollout Flag
// (legacy upstream-overlap mode only):
//
//   - RolloutOff      → request proxies to the upstream; Go handler not called.
//   - RolloutShadow   → request proxies to the upstream AND Go handler runs
//     in a goroutine on a cloned request with response
//     discarded. Used to validate response shape without
//     any user-visible risk.
//   - RolloutPercent  → percent% of requests go to the Go handler, the
//     rest proxy. Random per-request — for sticky
//     routing add a request-id-hash variant later.
//
// In STANDALONE mode (no upstream) the flag is moot: the native Go
// handler serves 100% of requests, whatever the flag says.
//
// The chosen path is logged at info on every request for observability.
func (s *Strangler) NativeFlagged(method, pattern string, h http.Handler, flag Flag) {
	if s.upstreamProxy == nil {
		s.router.Method(method, pattern, h)
		return
	}
	wrapped := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		logger := zerolog.Ctx(r.Context())
		switch flag.Mode {
		case RolloutOff:
			logger.Debug().Str("route", pattern).Str("decision", "proxy").Msg("strangler_decision")
			s.upstreamProxy.ServeHTTP(w, r)

		case RolloutShadow:
			// Buffer the body so both the proxy AND the shadow Go
			// handler can read it. Without this, the goroutine's
			// `r.Body` would already be drained by the proxy.
			body, _ := io.ReadAll(r.Body)
			_ = r.Body.Close()
			r.Body = io.NopCloser(bytes.NewReader(body))

			shadowReq := r.Clone(r.Context())
			shadowReq.Body = io.NopCloser(bytes.NewReader(body))

			go func() {
				defer func() {
					if rec := recover(); rec != nil {
						logger.Error().
							Interface("panic", rec).
							Str("route", pattern).
							Msg("strangler_shadow_panic")
					}
				}()
				// Discard the response — shadow runs for side-effect
				// observability only.
				h.ServeHTTP(discardResponseWriter{}, shadowReq)
			}()

			logger.Debug().Str("route", pattern).Str("decision", "proxy+shadow").Msg("strangler_decision")
			s.upstreamProxy.ServeHTTP(w, r)

		case RolloutPercent:
			// Random per-request. For sticky-per-user routing a
			// future variant should hash request_id / user_id.
			if rand.Intn(100) < flag.Percent {
				logger.Debug().Str("route", pattern).Str("decision", "native").Int("percent", flag.Percent).Msg("strangler_decision")
				h.ServeHTTP(w, r)
			} else {
				logger.Debug().Str("route", pattern).Str("decision", "proxy").Int("percent", flag.Percent).Msg("strangler_decision")
				s.upstreamProxy.ServeHTTP(w, r)
			}
		}
	})
	s.router.Method(method, pattern, wrapped)
}

// discardResponseWriter captures status/headers but discards body.
// Used by shadow rollouts so the goroutine can call the handler
// without retaining the response payload.
type discardResponseWriter struct {
	status int
	header http.Header
}

func (d discardResponseWriter) Header() http.Header {
	if d.header == nil {
		return http.Header{}
	}
	return d.header
}
func (d discardResponseWriter) Write(b []byte) (int, error) { return len(b), nil }
func (d discardResponseWriter) WriteHeader(status int)      { d.status = status }

// Mount attaches a sub-router that shares the same Strangler so its
// children behave the same (unmatched → proxy fallback in overlap
// mode, 404 in standalone mode).
func (s *Strangler) Mount(pattern string, h http.Handler) {
	s.router.Mount(pattern, h)
}

// ServeHTTP makes Strangler an http.Handler.
func (s *Strangler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.router.ServeHTTP(w, r)
}

// UpstreamURL returns the legacy upstream target, or "" in
// STANDALONE mode — used by ops tooling (health probes that ping the
// upstream, audit logs).
func (s *Strangler) UpstreamURL() string {
	if s.upstreamURL == nil {
		return ""
	}
	return s.upstreamURL.String()
}

// HasUpstream reports whether a legacy proxy upstream is configured.
func (s *Strangler) HasUpstream() bool {
	return s.upstreamProxy != nil
}

// dialTimeout is the upstream connect budget. Exposed for tests.
var dialTimeout = 5 * time.Second
