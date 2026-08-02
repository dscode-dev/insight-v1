// Search observability (Prometheus, registered on the shared gateway registry —
// no second telemetry architecture). Console dashboards consume these later.
//
//   search_requests_total{category}      — volume + category distribution
//                                          (searches/sec = rate() in PromQL)
//   search_latency_seconds{category}     — end-to-end handler latency
//   search_cache_events_total{result}    — hit | miss
//   search_partial_responses_total       — /all responses with partial=true
//   search_upstream_timeouts_total{category}
//   search_cancelled_total               — client disconnected mid-search
//   search_empty_results_total{category} — zero-item pages (product signal)
//   search_rate_limited_total            — per-user limiter rejections

package searchbff

import (
	"context"
	"errors"

	"github.com/prometheus/client_golang/prometheus"
)

type Metrics struct {
	requests    *prometheus.CounterVec
	latency     *prometheus.HistogramVec
	cacheEvents *prometheus.CounterVec
	partial     prometheus.Counter
	timeouts    *prometheus.CounterVec
	cancelled   prometheus.Counter
	empty       *prometheus.CounterVec
	rateLimited prometheus.Counter
}

func NewMetrics(reg prometheus.Registerer) *Metrics {
	m := &Metrics{
		requests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "search_requests_total",
			Help: "Search requests by category (all|users|agents|communities|competitions|matches|posts|history|capabilities).",
		}, []string{"category"}),
		latency: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "search_latency_seconds",
			Help:    "Search end-to-end latency by category.",
			Buckets: []float64{.01, .025, .05, .1, .25, .5, 1, 2.5, 5},
		}, []string{"category"}),
		cacheEvents: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "search_cache_events_total",
			Help: "Search cache lookups by result (hit|miss).",
		}, []string{"result"}),
		partial: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "search_partial_responses_total",
			Help: "Aggregated searches answered with partial=true.",
		}),
		timeouts: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "search_upstream_timeouts_total",
			Help: "Category fetches aborted by the global search timeout.",
		}, []string{"category"}),
		cancelled: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "search_cancelled_total",
			Help: "Searches aborted because the client cancelled/disconnected.",
		}),
		empty: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "search_empty_results_total",
			Help: "Search pages returning zero items, by category.",
		}, []string{"category"}),
		rateLimited: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "search_rate_limited_total",
			Help: "Search requests rejected by the per-user rate limiter.",
		}),
	}
	reg.MustRegister(m.requests, m.latency, m.cacheEvents, m.partial,
		m.timeouts, m.cancelled, m.empty, m.rateLimited)
	return m
}

func (m *Metrics) Request(category string)            { m.requests.WithLabelValues(category).Inc() }
func (m *Metrics) Latency(category string, s float64) { m.latency.WithLabelValues(category).Observe(s) }
func (m *Metrics) CacheHit()                          { m.cacheEvents.WithLabelValues("hit").Inc() }
func (m *Metrics) CacheMiss()                         { m.cacheEvents.WithLabelValues("miss").Inc() }
func (m *Metrics) Partial()                           { m.partial.Inc() }
func (m *Metrics) Cancelled()                         { m.cancelled.Inc() }
func (m *Metrics) Empty(category string)              { m.empty.WithLabelValues(category).Inc() }
func (m *Metrics) RateLimited()                       { m.rateLimited.Inc() }

// CategoryFailure classifies a fan-out failure: global-timeout expiry counts as
// a timeout for that category; other errors are surfaced via partial reporting.
func (m *Metrics) CategoryFailure(category string, err error, ctxErr error) {
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(ctxErr, context.DeadlineExceeded) {
		m.timeouts.WithLabelValues(category).Inc()
	}
}
