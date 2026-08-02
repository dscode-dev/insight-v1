package source

import (
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"
)

// Source is a registered provider in the Hub catalogue.
//
// Distinct from SourceRef: SourceRef is the per-event provenance
// stamp, Source is the long-lived registration. A SourceRef's
// SourceID is the canonical id of some Source in the registry —
// validation can (Sprint 2+) cross-check that the ref points at a
// known, enabled source.
//
// Fields:
//   - ID                 primary key (UUID)
//   - Name               human-friendly unique name (e.g. "API-Football v3")
//   - Type               SourceType enum
//   - Priority           lower = higher priority for conflict resolution;
//     0 reserved for "must override" intra-tier ties
//   - Enabled            disabled sources are still queryable but never
//     contribute to canonical confidence aggregation
//   - ConfidenceWeight   [0..1] static trust multiplier applied to every
//     raw event from this source by the confidence
//     policy (default product policy: weight × raw_confidence)
type Source struct {
	id               uuid.UUID
	name             string
	typ              SourceType
	priority         int
	enabled          bool
	confidenceWeight float64
}

const (
	maxSourceRegName = 128
	minPriority      = 0
)

var (
	ErrSourceMissingName      = errors.New("source: name is required")
	ErrSourceNameTooLong      = errors.New("source: name exceeds 128 chars")
	ErrSourceInvalidType      = errors.New("source: invalid source_type")
	ErrSourceNegativePriority = errors.New("source: priority must be >= 0")
	ErrSourceWeightOutOfRange = errors.New("source: confidence_weight outside [0,1]")
)

// New constructs a Source with full invariant enforcement. Use this
// at every registration boundary — never compose a Source by hand
// from raw fields.
//
// Returns a normalised value (trimmed name, lowercase type slug
// already validated). The id is caller-supplied so test fixtures can
// pin known UUIDs.
func New(
	id uuid.UUID,
	name string,
	typ SourceType,
	priority int,
	enabled bool,
	confidenceWeight float64,
) (*Source, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return nil, ErrSourceMissingName
	}
	if len(name) > maxSourceRegName {
		return nil, fmt.Errorf("%w: got %d", ErrSourceNameTooLong, len(name))
	}
	if !IsValid(typ) {
		return nil, fmt.Errorf("%w: %q", ErrSourceInvalidType, typ)
	}
	if priority < minPriority {
		return nil, fmt.Errorf("%w: got %d", ErrSourceNegativePriority, priority)
	}
	if confidenceWeight < 0 || confidenceWeight > 1 {
		return nil, fmt.Errorf("%w: got %.4f", ErrSourceWeightOutOfRange, confidenceWeight)
	}
	return &Source{
		id:               id,
		name:             name,
		typ:              typ,
		priority:         priority,
		enabled:          enabled,
		confidenceWeight: confidenceWeight,
	}, nil
}

// Reconstitute rebuilds from persisted state without re-validation.
// Repository constructors call this — the row already passed the
// invariants when it was inserted.
func Reconstitute(
	id uuid.UUID,
	name string,
	typ SourceType,
	priority int,
	enabled bool,
	confidenceWeight float64,
) *Source {
	return &Source{
		id:               id,
		name:             name,
		typ:              typ,
		priority:         priority,
		enabled:          enabled,
		confidenceWeight: confidenceWeight,
	}
}

// Accessors. State is private — mutations go through explicit
// behaviour methods so invariants stay enforced.
func (s *Source) ID() uuid.UUID             { return s.id }
func (s *Source) Name() string              { return s.name }
func (s *Source) Type() SourceType          { return s.typ }
func (s *Source) Priority() int             { return s.priority }
func (s *Source) Enabled() bool             { return s.enabled }
func (s *Source) ConfidenceWeight() float64 { return s.confidenceWeight }

// Enable / Disable — explicit state transitions. The repository
// observes these methods rather than letting callers flip the field
// directly, so future auditing (who/when) attaches in one place.
func (s *Source) Enable()  { s.enabled = true }
func (s *Source) Disable() { s.enabled = false }

// ChangeWeight applies a new confidence_weight under the same range
// invariant New enforces. Source admin endpoints route through here.
func (s *Source) ChangeWeight(w float64) error {
	if w < 0 || w > 1 {
		return fmt.Errorf("%w: got %.4f", ErrSourceWeightOutOfRange, w)
	}
	s.confidenceWeight = w
	return nil
}

// ChangePriority — same shape as ChangeWeight. Tier reshuffles are
// rare but happen (a previously trusted commercial_api gets demoted).
func (s *Source) ChangePriority(p int) error {
	if p < minPriority {
		return fmt.Errorf("%w: got %d", ErrSourceNegativePriority, p)
	}
	s.priority = p
	return nil
}
