package event

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

// RawSportsEvent is one observation from one source. It is NOT the
// platform truth — N raw events for the same Identity get merged
// into one CanonicalSportsEvent by the canonicalization service.
//
// Raw events are immutable post-construction. They're persisted
// once, queried by external_match_id or by canonical lineage join,
// and never updated. If the same provider re-observes the same
// underlying datum the duplicate is detected via raw_event_id
// (provider-supplied or Hub-derived) and rejected — see the
// duplicate_raw_event_id validation rule.
//
// CRITICAL: Source is a full SourceRef — the complete provenance,
// not a flattened source_id. The Hub MUST preserve every field.
type RawSportsEvent struct {
	rawEventID      uuid.UUID
	src             source.SourceRef
	sport           sport.Sport
	competitionID   uuid.UUID
	externalMatchID string
	eventType       string
	observedAt      time.Time
	payload         map[string]any
	rawConfidence   float64
}

// Domain errors for the raw event. The validation layer wraps these
// with the offending value for the wire response.
var (
	ErrRawMissingExternalMatchID = errors.New("raw_event: external_match_id required")
	ErrRawMissingEventType       = errors.New("raw_event: event_type required")
	ErrRawEmptyPayload           = errors.New("raw_event: payload must not be empty")
	ErrRawConfidenceRange        = errors.New("raw_event: raw_confidence outside [0,1]")
	ErrRawObservedAtMissing      = errors.New("raw_event: observed_at must be set")
	ErrRawCompetitionMissing     = errors.New("raw_event: competition_id required")
)

const maxExternalMatchIDLen = 128

// NewRaw constructs a RawSportsEvent with full invariant enforcement.
//
// The Source's own validation runs here too (via Validate) so
// callers can't smuggle a malformed SourceRef into a raw event —
// this matters because once persisted, the ref is the auditable
// truth about who supplied the data.
//
// The payload is shallow-copied (defensive against caller mutation
// after construction). For deep immutability the JSON serialisation
// at the persistence boundary completes the freeze.
func NewRaw(
	rawEventID uuid.UUID,
	src source.SourceRef,
	sportName sport.Sport,
	competitionID uuid.UUID,
	externalMatchID string,
	eventType string,
	observedAt time.Time,
	payload map[string]any,
	rawConfidence float64,
) (*RawSportsEvent, error) {
	if rawEventID == uuid.Nil {
		return nil, errors.New("raw_event: raw_event_id required")
	}
	if err := src.Validate(); err != nil {
		return nil, fmt.Errorf("raw_event: invalid source: %w", err)
	}
	if !sport.IsSupported(sportName) {
		return nil, fmt.Errorf("raw_event: unsupported sport %q: %w",
			sportName, sport.ErrUnsupportedSport)
	}
	if competitionID == uuid.Nil {
		return nil, ErrRawCompetitionMissing
	}
	if externalMatchID == "" {
		return nil, ErrRawMissingExternalMatchID
	}
	if len(externalMatchID) > maxExternalMatchIDLen {
		return nil, fmt.Errorf("raw_event: external_match_id exceeds %d chars",
			maxExternalMatchIDLen)
	}
	if eventType == "" {
		return nil, ErrRawMissingEventType
	}
	if observedAt.IsZero() {
		return nil, ErrRawObservedAtMissing
	}
	if len(payload) == 0 {
		return nil, ErrRawEmptyPayload
	}
	if rawConfidence < 0 || rawConfidence > 1 {
		return nil, fmt.Errorf("%w: got %.4f", ErrRawConfidenceRange, rawConfidence)
	}

	// Defensive shallow-copy. Caller can no longer mutate the map.
	clone := make(map[string]any, len(payload))
	for k, v := range payload {
		clone[k] = v
	}

	return &RawSportsEvent{
		rawEventID:      rawEventID,
		src:             src.Normalised(),
		sport:           sportName,
		competitionID:   competitionID,
		externalMatchID: externalMatchID,
		eventType:       eventType,
		observedAt:      observedAt.UTC(),
		payload:         clone,
		rawConfidence:   rawConfidence,
	}, nil
}

// ReconstituteRaw rebuilds without validation — for repository scans.
func ReconstituteRaw(
	rawEventID uuid.UUID,
	src source.SourceRef,
	sportName sport.Sport,
	competitionID uuid.UUID,
	externalMatchID string,
	eventType string,
	observedAt time.Time,
	payload map[string]any,
	rawConfidence float64,
) *RawSportsEvent {
	return &RawSportsEvent{
		rawEventID:      rawEventID,
		src:             src,
		sport:           sportName,
		competitionID:   competitionID,
		externalMatchID: externalMatchID,
		eventType:       eventType,
		observedAt:      observedAt,
		payload:         payload,
		rawConfidence:   rawConfidence,
	}
}

// Accessors. All fields private — RawSportsEvent is immutable after
// construction. Payload returns a SHALLOW COPY so callers can't
// mutate persisted state via the returned map.
func (r *RawSportsEvent) RawEventID() uuid.UUID    { return r.rawEventID }
func (r *RawSportsEvent) Source() source.SourceRef { return r.src }
func (r *RawSportsEvent) Sport() sport.Sport       { return r.sport }
func (r *RawSportsEvent) CompetitionID() uuid.UUID { return r.competitionID }
func (r *RawSportsEvent) ExternalMatchID() string  { return r.externalMatchID }
func (r *RawSportsEvent) EventType() string        { return r.eventType }
func (r *RawSportsEvent) ObservedAt() time.Time    { return r.observedAt }
func (r *RawSportsEvent) RawConfidence() float64   { return r.rawConfidence }

func (r *RawSportsEvent) Payload() map[string]any {
	out := make(map[string]any, len(r.payload))
	for k, v := range r.payload {
		out[k] = v
	}
	return out
}
