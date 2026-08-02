package event

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

// CanonicalSportsEvent is the platform truth — the result of merging
// N raw observations of the same Identity into one consensus view.
//
// Holds the COMPLETE list of contributing SourceRefs (lineage
// preservation rule), the merged payload, the lifecycle Status, and
// the policy-derived confidence score.
//
// Mutation is restricted to a small set of methods (AddSource,
// UpdateStatus, RecomputeConfidence) so the audit log can intercept
// every state change. Direct field writes from outside the package
// are impossible — fields are unexported.
type CanonicalSportsEvent struct {
	eventID       uuid.UUID
	sport         sport.Sport
	competitionID uuid.UUID
	season        string
	matchID       uuid.UUID
	eventType     string
	status        Status
	confidence    float64
	sources       []source.SourceRef
	occurredAt    time.Time
	payload       map[string]any
}

var (
	ErrCanonicalEventIDMissing    = errors.New("canonical_event: event_id required")
	ErrCanonicalMatchIDMissing    = errors.New("canonical_event: match_id required")
	ErrCanonicalEventTypeMissing  = errors.New("canonical_event: event_type required")
	ErrCanonicalPayloadEmpty      = errors.New("canonical_event: payload must not be empty")
	ErrCanonicalConfidenceRange   = errors.New("canonical_event: confidence outside [0,1]")
	ErrCanonicalOccurredAtMissing = errors.New("canonical_event: occurred_at required")
	ErrCanonicalNoSources         = errors.New("canonical_event: at least one source required")
	ErrCanonicalSeasonTooLong     = errors.New("canonical_event: season exceeds 16 chars")
)

const maxSeasonLen = 16

// NewCanonical constructs a canonical event with full invariant
// enforcement. Initial status is StatusCandidate — the application
// layer's status assignment routine promotes to Confirmed once
// enough corroborating raws + the absence of conflict are observed.
//
// The sources slice MUST be non-empty: a canonical event with no
// lineage violates the architectural rule.
func NewCanonical(
	eventID uuid.UUID,
	identity Identity,
	season string,
	occurredAt time.Time,
	payload map[string]any,
	sources []source.SourceRef,
	confidence float64,
) (*CanonicalSportsEvent, error) {
	if eventID == uuid.Nil {
		return nil, ErrCanonicalEventIDMissing
	}
	if identity.IsZero() {
		return nil, fmt.Errorf("canonical_event: identity incomplete")
	}
	if !sport.IsSupported(identity.Sport) {
		return nil, fmt.Errorf("canonical_event: unsupported sport %q: %w",
			identity.Sport, sport.ErrUnsupportedSport)
	}
	if identity.MatchID == uuid.Nil {
		return nil, ErrCanonicalMatchIDMissing
	}
	if identity.EventType == "" {
		return nil, ErrCanonicalEventTypeMissing
	}
	if occurredAt.IsZero() {
		return nil, ErrCanonicalOccurredAtMissing
	}
	if len(payload) == 0 {
		return nil, ErrCanonicalPayloadEmpty
	}
	if len(sources) == 0 {
		return nil, ErrCanonicalNoSources
	}
	if confidence < 0 || confidence > 1 {
		return nil, fmt.Errorf("%w: got %.4f", ErrCanonicalConfidenceRange, confidence)
	}
	if len(season) > maxSeasonLen {
		return nil, fmt.Errorf("%w: got %d", ErrCanonicalSeasonTooLong, len(season))
	}
	for _, s := range sources {
		if err := s.Validate(); err != nil {
			return nil, fmt.Errorf("canonical_event: invalid source ref: %w", err)
		}
	}

	// Defensive copies — see RawSportsEvent for the rationale.
	payloadClone := make(map[string]any, len(payload))
	for k, v := range payload {
		payloadClone[k] = v
	}
	sourcesClone := make([]source.SourceRef, len(sources))
	for i, s := range sources {
		sourcesClone[i] = s.Normalised()
	}

	return &CanonicalSportsEvent{
		eventID:       eventID,
		sport:         identity.Sport,
		competitionID: identity.CompetitionID,
		season:        season,
		matchID:       identity.MatchID,
		eventType:     identity.EventType,
		status:        StatusCandidate,
		confidence:    confidence,
		sources:       sourcesClone,
		occurredAt:    occurredAt.UTC(),
		payload:       payloadClone,
	}, nil
}

// ReconstituteCanonical rebuilds from a persisted row. Skips
// validation per the standard reconstitute pattern.
func ReconstituteCanonical(
	eventID uuid.UUID,
	identity Identity,
	season string,
	status Status,
	confidence float64,
	sources []source.SourceRef,
	occurredAt time.Time,
	payload map[string]any,
) *CanonicalSportsEvent {
	return &CanonicalSportsEvent{
		eventID:       eventID,
		sport:         identity.Sport,
		competitionID: identity.CompetitionID,
		season:        season,
		matchID:       identity.MatchID,
		eventType:     identity.EventType,
		status:        status,
		confidence:    confidence,
		sources:       sources,
		occurredAt:    occurredAt,
		payload:       payload,
	}
}

// Accessors. Defensive copies for the mutable collections.

func (c *CanonicalSportsEvent) EventID() uuid.UUID       { return c.eventID }
func (c *CanonicalSportsEvent) Sport() sport.Sport       { return c.sport }
func (c *CanonicalSportsEvent) CompetitionID() uuid.UUID { return c.competitionID }
func (c *CanonicalSportsEvent) Season() string           { return c.season }
func (c *CanonicalSportsEvent) MatchID() uuid.UUID       { return c.matchID }
func (c *CanonicalSportsEvent) EventType() string        { return c.eventType }
func (c *CanonicalSportsEvent) Status() Status           { return c.status }
func (c *CanonicalSportsEvent) Confidence() float64      { return c.confidence }
func (c *CanonicalSportsEvent) OccurredAt() time.Time    { return c.occurredAt }

func (c *CanonicalSportsEvent) Identity() Identity {
	return Identity{
		Sport:         c.sport,
		CompetitionID: c.competitionID,
		MatchID:       c.matchID,
		EventType:     c.eventType,
	}
}

func (c *CanonicalSportsEvent) Sources() []source.SourceRef {
	out := make([]source.SourceRef, len(c.sources))
	copy(out, c.sources)
	return out
}

func (c *CanonicalSportsEvent) Payload() map[string]any {
	out := make(map[string]any, len(c.payload))
	for k, v := range c.payload {
		out[k] = v
	}
	return out
}

// SourceCount — convenience for the confidence policy + tests.
func (c *CanonicalSportsEvent) SourceCount() int { return len(c.sources) }

// AddSource appends a new SourceRef to the lineage. Idempotent on
// (source_id, observed_at) — a re-ingestion of the same observation
// must not duplicate the lineage entry.
//
// Does NOT recompute confidence or status — those go through their
// dedicated methods so the orchestrator can sequence operations
// explicitly.
func (c *CanonicalSportsEvent) AddSource(ref source.SourceRef) error {
	if err := ref.Validate(); err != nil {
		return fmt.Errorf("canonical_event: rejecting invalid source: %w", err)
	}
	normalised := ref.Normalised()
	for _, existing := range c.sources {
		if existing.SourceID == normalised.SourceID &&
			existing.ObservedAt.Equal(normalised.ObservedAt) {
			return nil // idempotent
		}
	}
	c.sources = append(c.sources, normalised)
	return nil
}

// UpdateStatus transitions the canonical event. The validation layer
// enforces transition legality (e.g. can't move from rejected back to
// candidate). Here we only assert the new status is a known constant.
func (c *CanonicalSportsEvent) UpdateStatus(s Status) error {
	if !s.IsValid() {
		return fmt.Errorf("%w: %q", ErrInvalidStatus, s)
	}
	c.status = s
	return nil
}

// SetConfidence applies a new policy-derived confidence value. The
// orchestrator drives this via the ConfidenceService — callers
// don't compute confidence here directly.
func (c *CanonicalSportsEvent) SetConfidence(v float64) error {
	if v < 0 || v > 1 {
		return fmt.Errorf("%w: got %.4f", ErrCanonicalConfidenceRange, v)
	}
	c.confidence = v
	return nil
}

// ReplacePayload — used when the canonicalization service merges a
// new raw into the existing canonical and the merged payload changes.
// Empty payloads are rejected to preserve the original invariant.
func (c *CanonicalSportsEvent) ReplacePayload(p map[string]any) error {
	if len(p) == 0 {
		return ErrCanonicalPayloadEmpty
	}
	clone := make(map[string]any, len(p))
	for k, v := range p {
		clone[k] = v
	}
	c.payload = clone
	return nil
}
