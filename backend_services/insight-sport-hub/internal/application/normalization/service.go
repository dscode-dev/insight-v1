// Package normalization — NormalizerService.
//
// Sprint 1 scope: provider-agnostic normalization. The service
// accepts a generic NormalizedInput shape that adapter packages
// (Sprint 2: api_football, sportmonks, ...) will translate to from
// their provider-native types. The Hub itself NEVER imports adapter
// packages — that's the boundary the architecture tests enforce.
//
// What "normalize" means today:
//   - canonicalise sport string → sport.Sport
//   - apply SourceRef defaults (source_name from id, observed_at UTC)
//   - cap external_match_id length
//   - cast payload values into JSON-friendly types via a defensive
//     copy
//
// What it deliberately doesn't do:
//   - map external_match_id → canonical match UUID (that's the
//     match catalogue's job, ships in Sprint 2)
//   - merge multiple sources (canonicalisation service)
//   - compute confidence (confidence service)
//   - detect conflicts (conflict service)
package normalization

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

// NormalizedInput is the shape every adapter MUST produce. Pure-data,
// no behaviour — adapters fill the fields from their provider-native
// payload before handing off to NormalizerService.
type NormalizedInput struct {
	// Adapter-supplied id. The Hub re-uses if non-zero; otherwise
	// generates one. This is the de-dup key — if the adapter knows
	// it already saw this datum (e.g. API returned the same event_id
	// in a poll), reusing the id triggers the duplicate path.
	RawEventID uuid.UUID

	Source          source.SourceRef
	SportRaw        string
	CompetitionID   uuid.UUID
	ExternalMatchID string
	EventType       string
	ObservedAt      time.Time
	Payload         map[string]any
	RawConfidence   float64
}

type Service struct{}

func New() *Service { return &Service{} }

var (
	ErrNormalizeMissingPayload = errors.New("normalize: payload required")
	ErrNormalizeNilRaw         = errors.New("normalize: nil raw event")
)

// NormalizeRaw — Sprint 2.1 architectural pass-through.
//
// Provider adapters already emit `*event.RawSportsEvent` via their
// own mappers; routing that raw through NormalizerService here keeps
// a single architectural seam between "external producer" and the
// rest of the pipeline (validation → conflict → confidence → canon).
//
// Future producers — CrewAI agents, LangGraph workflows, internal
// bots, imported datasets — all land here too. The method is a
// pass-through today; if/when cross-producer normalisation lands
// (e.g. timestamp harmonisation across non-HTTP sources), the
// behaviour goes here without touching the orchestrator or adapters.
//
// What this method MUST NOT do:
//   - apply provider-specific shaping (that belongs in the mapper)
//   - mutate the SourceRef (lineage preservation rule)
//   - recompute confidence
//   - detect conflicts
//   - cross-reference other raws
func (s *Service) NormalizeRaw(raw *event.RawSportsEvent) (*event.RawSportsEvent, error) {
	if raw == nil {
		return nil, ErrNormalizeNilRaw
	}
	return raw, nil
}

// Normalize converts a NormalizedInput into a RawSportsEvent.
//
// Failures here surface domain errors (ErrUnsupportedSport,
// SourceRef.Validate errors, RawSportsEvent invariant errors) so
// the validation service can quarantine without inspecting nested
// types.
func (s *Service) Normalize(input NormalizedInput) (*event.RawSportsEvent, error) {
	sp, err := sport.Parse(input.SportRaw)
	if err != nil {
		return nil, fmt.Errorf("normalize: %w (sport=%q)", err, input.SportRaw)
	}

	id := input.RawEventID
	if id == uuid.Nil {
		id = uuid.New()
	}

	if len(input.Payload) == 0 {
		return nil, ErrNormalizeMissingPayload
	}

	// Defensive copy — the adapter mustn't mutate Payload after
	// handing it to the Hub. RawSportsEvent constructor also copies
	// but we copy here too so the failure paths below don't see a
	// shared reference if a future change introduces an early return.
	payload := make(map[string]any, len(input.Payload))
	for k, v := range input.Payload {
		payload[k] = v
	}

	raw, err := event.NewRaw(
		id,
		input.Source.Normalised(),
		sp,
		input.CompetitionID,
		input.ExternalMatchID,
		input.EventType,
		input.ObservedAt,
		payload,
		input.RawConfidence,
	)
	if err != nil {
		return nil, fmt.Errorf("normalize: %w", err)
	}
	return raw, nil
}
