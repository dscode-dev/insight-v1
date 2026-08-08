// FEATURE-COMMUNITIES-V1 Stage 2 — observability (Prometheus, shared registry).
//
//	community_requests_total{endpoint}        — volume by endpoint
//	community_latency_seconds{endpoint}       — end-to-end handler latency
//	community_cache_events_total{result}      — hit | miss (stats cache)
//	community_partial_responses_total         — detail responses with partial=true
//	community_upstream_timeouts_total{endpoint}
//	community_rate_limited_total              — per-user limiter rejections
package communitybff

import (
	"github.com/prometheus/client_golang/prometheus"
)

type Metrics struct {
	requests    *prometheus.CounterVec
	latency     *prometheus.HistogramVec
	cacheEvents *prometheus.CounterVec
	partial     prometheus.Counter
	timeouts    *prometheus.CounterVec
	rateLimited prometheus.Counter
}

func NewMetrics(reg prometheus.Registerer) *Metrics {
	m := &Metrics{
		requests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "community_requests_total",
			Help: "Community requests by endpoint (detail|members|discussions|join|leave).",
		}, []string{"endpoint"}),
		latency: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "community_latency_seconds",
			Help:    "Community handler end-to-end latency.",
			Buckets: prometheus.DefBuckets,
		}, []string{"endpoint"}),
		cacheEvents: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "community_cache_events_total",
			Help: "Community stats cache events (hit|miss).",
		}, []string{"result"}),
		partial: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "community_partial_responses_total",
			Help: "Community detail responses returned with partial=true.",
		}),
		timeouts: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "community_upstream_timeouts_total",
			Help: "Community upstream timeouts by endpoint.",
		}, []string{"endpoint"}),
		rateLimited: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "community_rate_limited_total",
			Help: "Community requests rejected by the per-user rate limiter.",
		}),
	}
	reg.MustRegister(m.requests, m.latency, m.cacheEvents, m.partial, m.timeouts, m.rateLimited)
	return m
}

func (m *Metrics) request(ep string) { m.requests.WithLabelValues(ep).Inc() }
func (m *Metrics) cacheHit()         { m.cacheEvents.WithLabelValues("hit").Inc() }
func (m *Metrics) cacheMiss()        { m.cacheEvents.WithLabelValues("miss").Inc() }
func (m *Metrics) partialInc()       { m.partial.Inc() }
func (m *Metrics) timeout(ep string) { m.timeouts.WithLabelValues(ep).Inc() }
func (m *Metrics) rateLimit()        { m.rateLimited.Inc() }
