package ports

// Metrics is the placeholder port for the observability counters
// listed in the Sprint 1 spec:
//
//	registered_sources       gauge — current count of enabled sources
//	raw_events_total         counter — every raw event ingested
//	canonical_events_total   counter — every canonical event created/updated
//	rejected_events_total    counter labelled by reason
//	conflicting_events_total counter labelled by identity-type
//
// Sprint 1 ships a no-op implementation. Sprint 2 wires Prometheus
// (via insight-runtime-go/pkg/metrics) — the only change at the
// composition root is which adapter satisfies this interface.
type Metrics interface {
	IncRawIngested()
	IncRawDuplicate()
	IncCanonicalUpserted()
	IncRejected(reason string)
	IncConflict(identityType string)
	SetRegisteredSources(n int)
}
