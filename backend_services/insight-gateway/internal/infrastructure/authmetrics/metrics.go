// Package authmetrics is the Prometheus implementation of
// application/auth.Metrics (Auth-A Part 10).
//
// Exposes:
//
//	auth_phone_provider_requests_total       — provider OTP send attempts
//	auth_phone_provider_verifications_total  — provider OTP verify attempts
//	auth_registrations_total                 — completed registrations
//	auth_logins_total                        — successful logins
//	auth_refresh_total                       — access/refresh rotations
//
// Counters only; provider counters are labeled by provider/result for success
// rate queries.
package authmetrics

import "github.com/prometheus/client_golang/prometheus"

type Metrics struct {
	phoneProviderRequests      *prometheus.CounterVec
	phoneProviderVerifications *prometheus.CounterVec
	registrations              prometheus.Counter
	logins                     prometheus.Counter
	refreshes                  prometheus.Counter
}

func New(reg prometheus.Registerer) *Metrics {
	m := &Metrics{
		phoneProviderRequests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "auth_phone_provider_requests_total",
			Help: "Gateway-orchestrated phone OTP request attempts by provider and result.",
		}, []string{"provider", "result"}),
		phoneProviderVerifications: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "auth_phone_provider_verifications_total",
			Help: "Gateway-orchestrated phone OTP verification attempts by provider and result.",
		}, []string{"provider", "result"}),
		registrations: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "auth_registrations_total",
			Help: "Completed Insight registrations.",
		}),
		logins: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "auth_logins_total",
			Help: "Successful Insight logins.",
		}),
		refreshes: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "auth_refresh_total",
			Help: "Successful access/refresh-token rotations.",
		}),
	}
	reg.MustRegister(
		m.phoneProviderRequests, m.phoneProviderVerifications,
		m.registrations, m.logins, m.refreshes,
	)
	return m
}

func (m *Metrics) PhoneProviderRequest(provider string, success bool) {
	m.phoneProviderRequests.WithLabelValues(provider, resultLabel(success)).Inc()
}

func (m *Metrics) PhoneProviderVerification(provider string, success bool) {
	m.phoneProviderVerifications.WithLabelValues(provider, resultLabel(success)).Inc()
}

func (m *Metrics) Login()        { m.logins.Inc() }
func (m *Metrics) Registration() { m.registrations.Inc() }
func (m *Metrics) Refresh()      { m.refreshes.Inc() }

func resultLabel(success bool) string {
	if success {
		return "success"
	}
	return "failure"
}
