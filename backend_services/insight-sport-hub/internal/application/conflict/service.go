// Package conflict — ConflictDetectionService.
//
// Decides whether two or more raws for the SAME Identity disagree
// enough to mark the canonical as `conflicting`.
//
// Sprint 1 default rule (simple + conservative):
//   - compare each raw's payload against the others field-by-field
//     using a shallow equality check on JSON-friendly values
//   - raws from candidate-tier sources (internal_bot/community/unknown)
//     are excluded from the comparison — they're never authoritative
//   - if ≥ 2 NON-candidate raws disagree on any shared key, conflict
//
// The rule is intentionally opt-in to pluggability — future sprints
// will introduce smarter strategies (e.g. weighted disagreement,
// field-level threshold per event_type). The current implementation
// is a stand-alone strategy struct so swapping it doesn't require
// touching the orchestrator.
package conflict

import (
	"reflect"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
)

// Strategy is the interface the orchestrator depends on. Sprint 1
// implements one concrete strategy (FieldEqualityStrategy); Sprint 2+
// can introduce alternatives without re-plumbing.
type Strategy interface {
	// Detect inspects the raws + the optional existing canonical and
	// reports whether a conflict exists. The strategy MUST be pure:
	// no I/O, deterministic for a given input — keeps the conflict
	// decision reproducible from cold storage.
	Detect(raws []*event.RawSportsEvent, existing *event.CanonicalSportsEvent) Result
}

// Result carries the boolean + an explanation (operator-readable).
// Empty Explanation when no conflict.
type Result struct {
	Conflicts   bool
	Explanation string
}

// FieldEqualityStrategy is the Sprint 1 default. Documented in the
// package doc.
type FieldEqualityStrategy struct{}

func NewFieldEqualityStrategy() *FieldEqualityStrategy { return &FieldEqualityStrategy{} }

func (s *FieldEqualityStrategy) Detect(
	raws []*event.RawSportsEvent,
	existing *event.CanonicalSportsEvent,
) Result {
	// Authoritative raws only.
	auth := make([]*event.RawSportsEvent, 0, len(raws))
	for _, r := range raws {
		if !r.Source().IsCandidate() {
			auth = append(auth, r)
		}
	}
	if len(auth) < 2 {
		return Result{} // need ≥2 authoritative raws to disagree
	}

	// Build a map[field]→set of distinct values across all auth raws.
	// First-wins record of which raw observed which value, just so
	// the explanation can name names.
	type observation struct {
		value any
		from  string
	}
	values := make(map[string][]observation)
	for _, r := range auth {
		p := r.Payload()
		for k, v := range p {
			values[k] = append(values[k], observation{value: v, from: r.Source().SourceID})
		}
	}

	for field, obs := range values {
		if len(obs) < 2 {
			continue
		}
		first := obs[0]
		for _, o := range obs[1:] {
			if !reflect.DeepEqual(first.value, o.value) {
				return Result{
					Conflicts:   true,
					Explanation: explain(field, first, o),
				}
			}
		}
	}
	_ = existing // not used in Sprint 1 — future strategies may compare
	return Result{}
}

// Service wraps the strategy + emits the conflict metric. Keeps the
// strategy itself pure.
type Service struct {
	strategy Strategy
	incFn    func(identityType string)
}

// MetricsHook is a thin function reference so this package doesn't
// import ports.Metrics directly — pure strategy code stays untainted
// by infra-side imports.
type MetricsHook func(identityType string)

func New(strategy Strategy, hook MetricsHook) *Service {
	if hook == nil {
		hook = func(string) {}
	}
	return &Service{strategy: strategy, incFn: hook}
}

// Detect runs the strategy, increments the metric on conflict, and
// returns the result.
func (s *Service) Detect(
	raws []*event.RawSportsEvent,
	existing *event.CanonicalSportsEvent,
) Result {
	r := s.strategy.Detect(raws, existing)
	if r.Conflicts && len(raws) > 0 {
		s.incFn(raws[0].EventType())
	}
	return r
}

func explain(field string, a, b struct {
	value any
	from  string
}) string {
	return "field=" + field + " disagrees: " +
		a.from + " says " + valueString(a.value) +
		" vs " + b.from + " says " + valueString(b.value)
}

func valueString(v any) string {
	if v == nil {
		return "<nil>"
	}
	// Avoid pulling in fmt/strconv here — Result.Explanation is
	// already operator-readable from the Sprintf in the orchestrator.
	switch t := v.(type) {
	case string:
		return t
	default:
		return reflect.TypeOf(t).String()
	}
}
