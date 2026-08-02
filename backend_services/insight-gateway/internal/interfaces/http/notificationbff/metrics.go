// FEATURE-NOTIFICATIONS-V1 Stage 2 — observability (Prometheus, shared registry).
//
//   notification_requests_total{endpoint}
//   notification_latency_seconds{endpoint}
//   notification_cache_events_total{result}     — unread-count cache hit|miss
//   notification_partial_responses_total        — list responses with partial=true
//   notification_upstream_timeouts_total{endpoint}
package notificationbff

import "github.com/prometheus/client_golang/prometheus"

type Metrics struct {
	requests    *prometheus.CounterVec
	latency     *prometheus.HistogramVec
	cacheEvents *prometheus.CounterVec
	partial     prometheus.Counter
	timeouts    *prometheus.CounterVec
}

func NewMetrics(reg prometheus.Registerer) *Metrics {
	m := &Metrics{
		requests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "notification_requests_total",
			Help: "Notification requests by endpoint (list|unread_count|mark_read|mark_all_read).",
		}, []string{"endpoint"}),
		latency: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "notification_latency_seconds",
			Help:    "Notification handler end-to-end latency.",
			Buckets: prometheus.DefBuckets,
		}, []string{"endpoint"}),
		cacheEvents: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "notification_cache_events_total",
			Help: "Unread-count cache events (hit|miss).",
		}, []string{"result"}),
		partial: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "notification_partial_responses_total",
			Help: "Notification list responses returned with partial=true.",
		}),
		timeouts: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "notification_upstream_timeouts_total",
			Help: "Notification upstream timeouts by endpoint.",
		}, []string{"endpoint"}),
	}
	reg.MustRegister(m.requests, m.latency, m.cacheEvents, m.partial, m.timeouts)
	return m
}

func (m *Metrics) request(ep string) { m.requests.WithLabelValues(ep).Inc() }
func (m *Metrics) cacheHit()         { m.cacheEvents.WithLabelValues("hit").Inc() }
func (m *Metrics) cacheMiss()        { m.cacheEvents.WithLabelValues("miss").Inc() }
func (m *Metrics) partialInc()       { m.partial.Inc() }
func (m *Metrics) timeout(ep string) { m.timeouts.WithLabelValues(ep).Inc() }
