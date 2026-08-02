// Package confidence — ConfidenceService + Policy.
//
// Mirrors the Atlas Sprint 0.1 design: pluggable policy interface,
// shipped with one production-grade default (WeightedAveragePolicy).
// The orchestrator never hardcodes the formula — swap policies at
// composition root.
//
// Default formula (WeightedAveragePolicy):
//
//	final_confidence = sum(source.confidence_weight × raw.raw_confidence)
//	                   ─────────────────────────────────────────────────
//	                                sum(source.confidence_weight)
//
// Notes:
//   - candidate-tier sources contribute with their declared weight
//     unchanged; the GLOBAL behaviour of treating candidate refs as
//     non-authoritative is handled by the conflict service, not here
//   - empty source list → confidence 0 (the caller MUST quarantine
//     before reaching this code path; the 0 fallback is a safety net)
//   - weights normalised → numeric noise rare, but the final value
//     is clamped to [0,1] defensively
package confidence

import (
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
)

// Policy is the strategy contract. Sprint 1 ships WeightedAverage.
type Policy interface {
	// Compute receives the contributing raws + the registered Source
	// for each (resolved by SourceID). Source may be nil when the
	// raw came from an unregistered source — the policy decides how
	// to handle (default: treat the ref's own confidence as the weight).
	Compute(raws []*event.RawSportsEvent, sources map[string]*source.Source) float64
}

// WeightedAveragePolicy — the Sprint 1 default. See package doc.
type WeightedAveragePolicy struct{}

func NewWeightedAveragePolicy() *WeightedAveragePolicy { return &WeightedAveragePolicy{} }

func (p *WeightedAveragePolicy) Compute(
	raws []*event.RawSportsEvent,
	sources map[string]*source.Source,
) float64 {
	if len(raws) == 0 {
		return 0
	}
	var numerator, denominator float64
	for _, r := range raws {
		ref := r.Source()
		weight := ref.Confidence // fallback when no registered Source
		if reg, ok := sources[ref.SourceID]; ok && reg.Enabled() {
			weight = reg.ConfidenceWeight()
		}
		numerator += weight * r.RawConfidence()
		denominator += weight
	}
	if denominator <= 0 {
		return 0
	}
	out := numerator / denominator
	if out < 0 {
		return 0
	}
	if out > 1 {
		return 1
	}
	return out
}

// Service wraps a Policy + provides the convenience method the
// orchestrator calls. Distinct from Policy so the orchestrator can
// stay policy-agnostic.
type Service struct {
	policy Policy
}

func New(policy Policy) *Service {
	if policy == nil {
		policy = NewWeightedAveragePolicy()
	}
	return &Service{policy: policy}
}

// Compute resolves to the policy's Compute. Lives as a method on
// Service (not just the policy interface) so future cross-cutting
// concerns — caching, metrics emission, audit logging — attach
// without changing every call site.
func (s *Service) Compute(
	raws []*event.RawSportsEvent,
	sources map[string]*source.Source,
) float64 {
	return s.policy.Compute(raws, sources)
}
