// Package modmetrics is the Prometheus implementation of
// application/moderation.Metrics (Store-A).
//
// Exposes:
//
//	moderation_blocks_total{action}     — block / unblock
//	moderation_reports_total{reason}    — reports by reason
//	moderation_actions_total{action}    — admin moderation actions
package modmetrics

import "github.com/prometheus/client_golang/prometheus"

type Metrics struct {
	blocks  *prometheus.CounterVec
	reports *prometheus.CounterVec
	actions *prometheus.CounterVec
}

func New(reg prometheus.Registerer) *Metrics {
	m := &Metrics{
		blocks: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "moderation_blocks_total",
			Help: "User block/unblock actions (label: action).",
		}, []string{"action"}),
		reports: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "moderation_reports_total",
			Help: "Content reports filed (label: reason).",
		}, []string{"reason"}),
		actions: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "moderation_actions_total",
			Help: "Admin moderation actions taken (label: action).",
		}, []string{"action"}),
	}
	reg.MustRegister(m.blocks, m.reports, m.actions)
	return m
}

func (m *Metrics) Block(action string)            { m.blocks.WithLabelValues(action).Inc() }
func (m *Metrics) Report(reason string)           { m.reports.WithLabelValues(reason).Inc() }
func (m *Metrics) ModerationAction(action string) { m.actions.WithLabelValues(action).Inc() }
