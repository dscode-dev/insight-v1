// Package source — Source aggregate + SourceRef value object + types.
//
// SourceType slugs are the contract surface for cross-language wire
// compatibility. They mirror the Python `atlas.contracts.SourceType`
// (insight-atlas/atlas/contracts/source.py) byte-for-byte. NEVER
// reorder, rename or remove a slug. Future additions are additive-only,
// appended at the end of the constant block.
package source

import "errors"

// SourceType categorises where data originated. Stored as the lowercase
// string slug on the wire and in Postgres VARCHAR columns.
type SourceType string

const (
	// official_api — league/governing-body API direct.
	TypeOfficialAPI SourceType = "official_api"
	// commercial_api — licensed third-party data provider (api_football, sportmonks).
	TypeCommercialAPI SourceType = "commercial_api"
	// official_club — club's verified official channel.
	TypeOfficialClub SourceType = "official_club"
	// official_league — league's verified official channel.
	TypeOfficialLeague SourceType = "official_league"
	// trusted_media — vetted press partner.
	TypeTrustedMedia SourceType = "trusted_media"
	// internal_bot — Hub/Atlas crawler. CANDIDATE-only; never official fact.
	TypeInternalBot SourceType = "internal_bot"
	// community — user-generated (signals, posts, sentiment).
	TypeCommunity SourceType = "community"
	// unknown — ingested before provenance was tagged.
	TypeUnknown SourceType = "unknown"
)

// allTypes is the canonical enumeration used by IsValid + iteration.
// Order matches the constant block above (which mirrors Atlas).
var allTypes = []SourceType{
	TypeOfficialAPI,
	TypeCommercialAPI,
	TypeOfficialClub,
	TypeOfficialLeague,
	TypeTrustedMedia,
	TypeInternalBot,
	TypeCommunity,
	TypeUnknown,
}

// AllTypes returns a copy of every valid SourceType. The copy
// guarantees callers can't mutate the canonical list by accident.
func AllTypes() []SourceType {
	out := make([]SourceType, len(allTypes))
	copy(out, allTypes)
	return out
}

// IsValid returns true when t matches one of the declared SourceType
// constants. Cheap to call — used at every external boundary.
func IsValid(t SourceType) bool {
	for _, v := range allTypes {
		if v == t {
			return true
		}
	}
	return false
}

// IsCandidate reports whether this source type must be treated as a
// candidate signal rather than confirmed fact. Mirrors the helper of
// the same name on the Python side. The set is intentionally narrow:
// internal_bot, community, unknown.
//
// Downstream consumers (ML, frontend) MUST NOT promote candidate-
// sourced events to official-truth surfaces. The Hub uses this to
// gate confidence weighting + status assignment.
func IsCandidate(t SourceType) bool {
	switch t {
	case TypeInternalBot, TypeCommunity, TypeUnknown:
		return true
	default:
		return false
	}
}

// ErrUnknownSourceType is the canonical error for slugs that aren't
// in the declared enumeration.
var ErrUnknownSourceType = errors.New("source: unknown source_type")

// ParseSourceType normalises an inbound string. Empty/unknown values
// resolve to ErrUnknownSourceType so callers can decide whether to
// quarantine or default to TypeUnknown explicitly.
func ParseSourceType(raw string) (SourceType, error) {
	t := SourceType(raw)
	if !IsValid(t) {
		return "", ErrUnknownSourceType
	}
	return t, nil
}
