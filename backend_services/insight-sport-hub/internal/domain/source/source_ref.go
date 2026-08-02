package source

import (
	"errors"
	"fmt"
	"time"
)

// SourceRef is the full provenance descriptor for one observation.
//
// CRITICAL ARCHITECTURAL RULE (per Sprint 1 spec): every Raw and
// every Canonical event MUST preserve the COMPLETE SourceRef object.
// The Hub never flattens, simplifies or discards SourceRef fields.
// Lineage preservation is a first-class architectural requirement —
// loss of provenance is a violation, not a bug.
//
// Wire-compatible with atlas.contracts.SourceRef (Python). The Go
// representation chooses the same field names + JSON tags so a
// payload produced by either side deserialises into the other
// without a translator.
//
// Field semantics:
//   - SourceID         canonical id (≤64 chars, e.g. "api_football")
//   - SourceName       human label (≤128 chars; falls back to id if empty)
//   - Type             one of source.SourceType (mirrored across services)
//   - Confidence       trust this observation had IN the source [0..1]
//   - ObservedAt       when the producer observed the data (NOT ingestion)
//   - AdapterVersion   "{adapter}@{semver}" — null for community/user refs
//   - Metadata         opaque per-adapter bag (endpoint, etag, headers, …)
type SourceRef struct {
	SourceID       string         `json:"source_id"`
	SourceName     string         `json:"source_name"`
	Type           SourceType     `json:"source_type"`
	Confidence     float64        `json:"confidence"`
	ObservedAt     time.Time      `json:"observed_at"`
	AdapterVersion *string        `json:"adapter_version,omitempty"`
	Metadata       map[string]any `json:"metadata,omitempty"`
}

// SourceRef validation errors. Domain-level; the application layer
// wraps these with the offending value for the wire response.
var (
	ErrSourceRefMissingID         = errors.New("source_ref: missing source_id")
	ErrSourceRefIDTooLong         = errors.New("source_ref: source_id exceeds 64 chars")
	ErrSourceRefNameTooLong       = errors.New("source_ref: source_name exceeds 128 chars")
	ErrSourceRefAdapterTooLong    = errors.New("source_ref: adapter_version exceeds 64 chars")
	ErrSourceRefConfidenceRange   = errors.New("source_ref: confidence outside [0,1]")
	ErrSourceRefObservedAtMissing = errors.New("source_ref: observed_at must be set")
	ErrSourceRefObservedAtNaive   = errors.New("source_ref: observed_at must be timezone-aware (UTC)")
)

const (
	maxSourceIDLen   = 64
	maxSourceNameLen = 128
	maxAdapterVerLen = 64
)

// Validate enforces the SourceRef invariants. Called at every external
// ingestion boundary BEFORE the ref reaches a domain aggregate.
// Returning the first failure keeps the error chain single-cause.
//
// Mirrors the validators on the Python side so a payload accepted by
// one runtime is accepted by the other.
func (r SourceRef) Validate() error {
	if r.SourceID == "" {
		return ErrSourceRefMissingID
	}
	if len(r.SourceID) > maxSourceIDLen {
		return fmt.Errorf("%w: got %d", ErrSourceRefIDTooLong, len(r.SourceID))
	}
	if len(r.SourceName) > maxSourceNameLen {
		return fmt.Errorf("%w: got %d", ErrSourceRefNameTooLong, len(r.SourceName))
	}
	if r.AdapterVersion != nil && len(*r.AdapterVersion) > maxAdapterVerLen {
		return fmt.Errorf("%w: got %d", ErrSourceRefAdapterTooLong, len(*r.AdapterVersion))
	}
	if r.Confidence < 0 || r.Confidence > 1 {
		return fmt.Errorf("%w: got %.4f", ErrSourceRefConfidenceRange, r.Confidence)
	}
	if r.ObservedAt.IsZero() {
		return ErrSourceRefObservedAtMissing
	}
	if r.ObservedAt.Location() == nil {
		// Go time.Time always has a Location, so this is mostly belt-
		// and-suspenders. Explicit check on UTC consistency happens
		// at the persistence boundary (the postgres adapter forces
		// timestamptz).
		return ErrSourceRefObservedAtNaive
	}
	return nil
}

// Normalised returns a copy with the Sprint 0.1.1 fallbacks applied:
// SourceName defaulted from SourceID when empty, Metadata initialised
// to a non-nil empty map (so JSON marshalling doesn't drop a `null`
// when the wire contract expects `{}`).
//
// Pure — never mutates the receiver. Application services call this
// once at ingestion + persist the normalised form so downstream
// consumers always see a fully-populated ref.
func (r SourceRef) Normalised() SourceRef {
	out := r
	if out.SourceName == "" {
		out.SourceName = out.SourceID
	}
	if out.Metadata == nil {
		out.Metadata = map[string]any{}
	}
	out.ObservedAt = out.ObservedAt.UTC()
	return out
}

// IsCandidate exposes the type-level helper at the ref level for
// convenience — the application's status assignment + confidence
// weighting paths both branch on this predicate frequently.
func (r SourceRef) IsCandidate() bool {
	return IsCandidate(r.Type)
}
