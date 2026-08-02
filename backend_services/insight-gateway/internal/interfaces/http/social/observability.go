// Social BFF observability — Sprint 2.5 Part 13.
//
// One Metrics struct registered on the gateway's Prometheus registry
// (same pattern as the realtime broker). The HTTP middleware records
// request totals + latency per route; the handlers record the
// domain-level counters (feed reads, post writes, relationship +
// mute actions). Nil-safe: a nil *Metrics disables instrumentation
// (unit tests don't need a registry).
package social

import (
	"net/http"
	"strconv"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

type Metrics struct {
	requestsTotal *prometheus.CounterVec
	errorsTotal   *prometheus.CounterVec
	latency       *prometheus.HistogramVec
	feedReads     *prometheus.CounterVec
	postWrites    *prometheus.CounterVec
	followActions *prometheus.CounterVec
	muteActions   *prometheus.CounterVec
}

func NewMetrics(reg prometheus.Registerer) *Metrics {
	m := &Metrics{
		requestsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_social_requests_total",
			Help: "Social BFF requests, by route and status class.",
		}, []string{"route", "status"}),
		errorsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_social_errors_total",
			Help: "Social BFF error responses (4xx/5xx), by route.",
		}, []string{"route"}),
		latency: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "gateway_social_latency_seconds",
			Help:    "Social BFF request latency.",
			Buckets: []float64{.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5},
		}, []string{"route"}),
		feedReads: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_feed_reads_total",
			Help: "Feed reads proxied to Social, by feed kind.",
		}, []string{"feed"}),
		postWrites: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_post_writes_total",
			Help: "Post-surface writes (create/delete/comment).",
		}, []string{"action"}),
		followActions: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_follow_actions_total",
			Help: "Follow/unfollow actions.",
		}, []string{"action"}),
		muteActions: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_mute_actions_total",
			Help: "Mute/unmute actions.",
		}, []string{"action"}),
	}
	reg.MustRegister(
		m.requestsTotal, m.errorsTotal, m.latency,
		m.feedReads, m.postWrites, m.followActions, m.muteActions,
	)
	return m
}

// Instrument wraps one Social BFF route with request/latency/error
// accounting. Route label is the PATTERN (not the raw path) so
// cardinality stays bounded.
func (m *Metrics) Instrument(route string, next http.HandlerFunc) http.HandlerFunc {
	if m == nil {
		return next
	}
	return func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next(rec, r)
		m.latency.WithLabelValues(route).Observe(time.Since(started).Seconds())
		m.requestsTotal.WithLabelValues(
			route, strconv.Itoa(rec.status/100*100),
		).Inc()
		if rec.status >= 400 {
			m.errorsTotal.WithLabelValues(route).Inc()
		}
	}
}

func (m *Metrics) feedRead(kind string) {
	if m != nil {
		m.feedReads.WithLabelValues(kind).Inc()
	}
}

func (m *Metrics) postWrite(action string) {
	if m != nil {
		m.postWrites.WithLabelValues(action).Inc()
	}
}

func (m *Metrics) reaction(action string) {
	// Likes count as post-surface writes for traffic purposes.
	if m != nil {
		m.postWrites.WithLabelValues(action).Inc()
	}
}

func (m *Metrics) relationship(action string) {
	if m == nil {
		return
	}
	switch action {
	case "follow", "unfollow":
		m.followActions.WithLabelValues(action).Inc()
	case "mute", "unmute":
		m.muteActions.WithLabelValues(action).Inc()
	}
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}
