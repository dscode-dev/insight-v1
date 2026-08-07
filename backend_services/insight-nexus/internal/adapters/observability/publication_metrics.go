// Sprint 4 publication-engine metrics. Names are the Part 17 contract:
//
//	nexus_publications_total{agent}
//	nexus_publication_failures_total{agent,stage}
//	nexus_drafts_generated_total{agent}      (LLM-composed drafts)
//	nexus_provider_health{provider}          (1 healthy / 0.5 degraded / 0 offline)
//	nexus_llm_latency_seconds{provider}
//	nexus_fallbacks_total{provider}
//	nexus_tickets_created_total{agent}
//	nexus_spam_prevented_total{rule}
//	nexus_post_publish_bookkeeping_failures_total{agent,step}
package observability

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	"github.com/konoha-labs/insight-nexus/internal/application/llmrouter"
)

type PublicationMetrics struct {
	publications  *prometheus.CounterVec
	failures      *prometheus.CounterVec
	drafts        *prometheus.CounterVec
	providerHlth  *prometheus.GaugeVec
	llmLatency    *prometheus.HistogramVec
	fallbacks     *prometheus.CounterVec
	tickets       *prometheus.CounterVec
	spamPrevented *prometheus.CounterVec
	bookkeeping   *prometheus.CounterVec
}

func NewPublicationMetrics() *PublicationMetrics {
	return &PublicationMetrics{
		publications: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "nexus_publications_total",
			Help: "Agent posts published to Social, by agent.",
		}, []string{"agent"}),
		failures: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "nexus_publication_failures_total",
			Help: "Publication attempts that did not publish, by agent and stage (suppressed/invalid/social).",
		}, []string{"agent", "stage"}),
		drafts: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "nexus_drafts_generated_total",
			Help: "LLM-composed drafts produced, by agent.",
		}, []string{"agent"}),
		providerHlth: promauto.NewGaugeVec(prometheus.GaugeOpts{
			Name: "nexus_provider_health",
			Help: "Provider routing status: 1 healthy, 0.5 degraded, 0 offline.",
		}, []string{"provider"}),
		llmLatency: promauto.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "nexus_llm_latency_seconds",
			Help:    "LLM generation latency, by provider.",
			Buckets: []float64{.1, .25, .5, 1, 2, 4, 8, 15, 30, 60},
		}, []string{"provider"}),
		fallbacks: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "nexus_fallbacks_total",
			Help: "Provider failovers (a provider failed, the chain continued).",
		}, []string{"provider"}),
		tickets: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "nexus_tickets_created_total",
			Help: "Publication tickets created after all providers failed, by agent.",
		}, []string{"agent"}),
		spamPrevented: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "nexus_spam_prevented_total",
			Help: "Publications suppressed by anti-spam budgets, by rule.",
		}, []string{"rule"}),
		// Bookkeeping that runs AFTER the post is already on Social, so it
		// cannot fail the publication and cannot be retried by redelivery
		// (that would post twice). A non-zero value means the anti-spam
		// budget or the repetition memory is missing an entry — the agent
		// may post again sooner, or repeat itself.
		bookkeeping: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "nexus_post_publish_bookkeeping_failures_total",
			Help: "Writes that failed after a post already reached Social, by agent and step (antispam_log/publication_memory).",
		}, []string{"agent", "step"}),
	}
}

// ---- publisher.Metrics ----

func (m *PublicationMetrics) DraftComposed(agent string) {
	m.drafts.WithLabelValues(agent).Inc()
}

func (m *PublicationMetrics) Published(agent string) {
	m.publications.WithLabelValues(agent).Inc()
}

func (m *PublicationMetrics) PublicationFailed(agent, stage string) {
	m.failures.WithLabelValues(agent, stage).Inc()
}

func (m *PublicationMetrics) TicketCreated(agent string) {
	m.tickets.WithLabelValues(agent).Inc()
}

// ---- antispam.Metrics ----

func (m *PublicationMetrics) PostPublishBookkeepingFailed(agent, step string) {
	m.bookkeeping.WithLabelValues(agent, step).Inc()
}

func (m *PublicationMetrics) SpamPrevented(rule string) {
	m.spamPrevented.WithLabelValues(rule).Inc()
}

// ---- llmrouter.HealthMetrics + RouterMetrics ----

func (m *PublicationMetrics) ProviderHealth(provider string, status llmrouter.Status) {
	v := 0.0
	switch status {
	case llmrouter.StatusHealthy:
		v = 1.0
	case llmrouter.StatusDegraded:
		v = 0.5
	}
	m.providerHlth.WithLabelValues(provider).Set(v)
}

func (m *PublicationMetrics) LLMLatency(provider string, seconds float64) {
	m.llmLatency.WithLabelValues(provider).Observe(seconds)
}

func (m *PublicationMetrics) Fallback(from, _ string) {
	m.fallbacks.WithLabelValues(from).Inc()
}
