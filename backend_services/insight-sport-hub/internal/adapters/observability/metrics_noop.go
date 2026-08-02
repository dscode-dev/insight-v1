// Package observability — Sprint 1 placeholder Metrics adapter.
//
// Implements ports.Metrics with empty bodies. Sprint 2 swaps in
// the Prometheus-backed adapter (driven by
// insight-runtime-go/pkg/metrics) — only the constructor at the
// composition root changes.
package observability

type NoopMetrics struct{}

func NewNoopMetrics() *NoopMetrics { return &NoopMetrics{} }

func (NoopMetrics) IncRawIngested()                 {}
func (NoopMetrics) IncRawDuplicate()                {}
func (NoopMetrics) IncCanonicalUpserted()           {}
func (NoopMetrics) IncRejected(reason string)       {}
func (NoopMetrics) IncConflict(identityType string) {}
func (NoopMetrics) SetRegisteredSources(n int)      {}
