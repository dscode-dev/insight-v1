package event

import (
	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

// Identity is the natural key of a CanonicalSportsEvent.
//
// Two RawSportsEvents that share this 4-tuple are observations of
// the SAME platform-truth event — they're candidates for merge,
// agreement check, or conflict detection. The Hub uses Identity to
// look up "is there already a canonical for this?" before deciding
// to create new vs update existing.
//
// (Sport, Competition, Match, Type) was chosen over a surrogate UUID
// because:
//  1. Different providers won't share a surrogate, so we'd need a
//     mapping table anyway.
//  2. The natural key is stable across replays + back-fills.
//  3. Conflict detection is "did two raws with the same identity
//     report different payloads?" — that's a direct equality check
//     on Identity, no lookup.
//
// EventType is intentionally a free-form string here (not an enum)
// so adapters can declare provider-native event types like
// "match.started", "goal", "lineup_published" without the Hub
// pre-knowing every variant. Validation only checks non-empty.
type Identity struct {
	Sport         sport.Sport
	CompetitionID uuid.UUID
	MatchID       uuid.UUID
	EventType     string
}

// Equal reports field-by-field equality. Used in conflict detection
// + lineage joins. The receiver is a value, not pointer — Identity
// is a small struct, copying is cheap.
func (i Identity) Equal(other Identity) bool {
	return i.Sport == other.Sport &&
		i.CompetitionID == other.CompetitionID &&
		i.MatchID == other.MatchID &&
		i.EventType == other.EventType
}

// IsZero reports whether any required component is missing. Useful
// for defensive checks in the orchestrator; full validation lives
// in the validation service.
func (i Identity) IsZero() bool {
	return i.Sport == "" ||
		i.CompetitionID == uuid.Nil ||
		i.MatchID == uuid.Nil ||
		i.EventType == ""
}
