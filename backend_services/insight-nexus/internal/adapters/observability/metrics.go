// Package observability — Nexus Prometheus metrics.
//
// Metric names are the Sprint 2 contract — never rename:
//
//	nexus_trends_consumed_total
//	agent_drafts_generated_total{agent}
//	agent_memory_hits_total
//	agent_memory_misses_total
//	agent_queue_depth{agent}
//	agent_publication_candidates_total{agent}
package observability

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type Metrics struct {
	trendsConsumed   prometheus.Counter
	draftsGenerated  *prometheus.CounterVec
	memoryHits       prometheus.Counter
	memoryMisses     prometheus.Counter
	queueDepth       *prometheus.GaugeVec
	publicationCands *prometheus.CounterVec
}

// New registers the Nexus metric set on the default registry.
func New() *Metrics {
	return &Metrics{
		trendsConsumed: promauto.NewCounter(prometheus.CounterOpts{
			Name: "nexus_trends_consumed_total",
			Help: "Atlas trends consumed off insight:stream:trends.",
		}),
		draftsGenerated: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "agent_drafts_generated_total",
			Help: "Structured drafts generated, by agent.",
		}, []string{"agent"}),
		memoryHits: promauto.NewCounter(prometheus.CounterOpts{
			Name: "agent_memory_hits_total",
			Help: "Context builds that found prior agent memories.",
		}),
		memoryMisses: promauto.NewCounter(prometheus.CounterOpts{
			Name: "agent_memory_misses_total",
			Help: "Context builds with no prior agent memories.",
		}),
		queueDepth: promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "agent_queue_depth",
			Help: "Current depth of each agent's publishing queue.",
		}, []string{"agent"}),
		publicationCands: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "agent_publication_candidates_total",
			Help: "Drafts recorded as publication candidates, by agent.",
		}, []string{"agent"}),
	}
}

// ---- pipeline.Metrics ----

func (m *Metrics) TrendConsumed()                    { m.trendsConsumed.Inc() }
func (m *Metrics) DraftGenerated(agent string)       { m.draftsGenerated.WithLabelValues(agent).Inc() }
func (m *Metrics) PublicationCandidate(agent string) { m.publicationCands.WithLabelValues(agent).Inc() }

// ---- contextbuilder.MetricsRecorder ----

func (m *Metrics) MemoryHit()  { m.memoryHits.Inc() }
func (m *Metrics) MemoryMiss() { m.memoryMisses.Inc() }

// SetQueueDepth — the queue-depth poller publishes gauges here.
func (m *Metrics) SetQueueDepth(agent string, depth int64) {
	m.queueDepth.WithLabelValues(agent).Set(float64(depth))
}

// Handler — the /metrics endpoint.
func Handler() http.Handler { return promhttp.Handler() }
