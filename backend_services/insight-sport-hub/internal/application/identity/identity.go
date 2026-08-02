// Package identity — Sprint 6.2 cross-provider match identity.
//
// API-Football, Football-Data and The Odds API each mint their own
// match ids. Without reconciliation, Atlas sees three separate entities
// for one fixture (Brazil vs Argentina) and cannot unify context, odds,
// statistics or inference.
//
// This package resolves a provider-specific match observation into a
// single canonical_match_id using four fixture-intrinsic signals:
//
//	competition  +  home team  +  away team  +  scheduled kickoff
//
// Resolution is precision-first:
//
//  1. exact alias lookup        (provider, external_id) → canonical id
//  2. fuzzy match within a configurable kickoff tolerance window, on
//     the canonical competition + normalised team names
//  3. mint a new canonical id (deterministic UUIDv5) + register the alias
//
// Provider ids are NEVER discarded — they are preserved as aliases so
// every observation remains traceable to its origin. The canonical
// competition id is already unified across providers by the Hub's
// CompetitionRegistry, so only team names + kickoff vary here.
package identity

import (
	"context"
	"strings"
	"time"
	"unicode"

	"github.com/google/uuid"
)

// DefaultKickoffTolerance absorbs provider scheduling drift (different
// feeds report slightly different kickoff times for the same fixture).
const DefaultKickoffTolerance = 90 * time.Minute

// canonicalNamespace seeds the deterministic UUIDv5 mint so the same
// fixture attributes always produce the same canonical id across
// processes + replays.
var canonicalNamespace = uuid.MustParse("6f1c2d34-5a6b-4c7d-8e9f-0a1b2c3d4e5f")

// ProviderMatchIdentity is what one provider observation knows about a
// match. ExternalID is the provider-native match id (preserved as an
// alias). Kickoff is the scheduled start in any timezone.
type ProviderMatchIdentity struct {
	Provider      string
	ExternalID    string
	CompetitionID uuid.UUID
	HomeTeam      string
	AwayTeam      string
	Kickoff       time.Time
}

// CanonicalMatch is the resolved cross-provider identity. Team names
// are stored normalised so future lookups are stable.
type CanonicalMatch struct {
	CanonicalMatchID uuid.UUID
	CompetitionID    uuid.UUID
	HomeTeam         string
	AwayTeam         string
	Kickoff          time.Time
}

// MatchAlias links a provider's external id to a canonical match.
type MatchAlias struct {
	Provider         string
	ExternalID       string
	CanonicalMatchID uuid.UUID
}

// Registry persists canonical matches + their provider aliases.
// Implementations: in-memory (this package) for the Hub process, and a
// persistent store on the Atlas side.
type Registry interface {
	// AliasLookup resolves a known (provider, external_id) alias.
	AliasLookup(ctx context.Context, provider, externalID string) (uuid.UUID, bool, error)
	// FindWithinTolerance finds an existing canonical match for the
	// competition + normalised teams whose kickoff is within tol.
	FindWithinTolerance(
		ctx context.Context, competitionID uuid.UUID,
		normHome, normAway string, kickoff time.Time, tol time.Duration,
	) (CanonicalMatch, bool, error)
	// Save upserts the canonical match + registers the alias.
	Save(ctx context.Context, match CanonicalMatch, alias MatchAlias) error
}

// Resolver turns provider observations into canonical match ids.
type Resolver struct {
	registry  Registry
	tolerance time.Duration
}

// NewResolver builds a resolver. A non-positive tolerance falls back to
// DefaultKickoffTolerance.
func NewResolver(registry Registry, tolerance time.Duration) *Resolver {
	if tolerance <= 0 {
		tolerance = DefaultKickoffTolerance
	}
	return &Resolver{registry: registry, tolerance: tolerance}
}

// Resolve returns the canonical_match_id for a provider observation,
// registering the alias as a side effect. When the observation lacks
// the team/kickoff signals needed for fuzzy matching (e.g. a
// competition-level event), it falls back to a deterministic mint keyed
// on whatever identity is available so the call never fails.
func (r *Resolver) Resolve(ctx context.Context, pmi ProviderMatchIdentity) (uuid.UUID, error) {
	// 1. Exact alias — O(1), authoritative.
	if id, ok, err := r.registry.AliasLookup(ctx, pmi.Provider, pmi.ExternalID); err != nil {
		return uuid.Nil, err
	} else if ok {
		return id, nil
	}

	normHome := Normalize(pmi.HomeTeam)
	normAway := Normalize(pmi.AwayTeam)

	// 2. Fuzzy within tolerance — only when we have both teams + a
	// kickoff to match on.
	if normHome != "" && normAway != "" && !pmi.Kickoff.IsZero() {
		match, ok, err := r.registry.FindWithinTolerance(
			ctx, pmi.CompetitionID, normHome, normAway, pmi.Kickoff, r.tolerance,
		)
		if err != nil {
			return uuid.Nil, err
		}
		if ok {
			alias := MatchAlias{Provider: pmi.Provider, ExternalID: pmi.ExternalID, CanonicalMatchID: match.CanonicalMatchID}
			if err := r.registry.Save(ctx, match, alias); err != nil {
				return uuid.Nil, err
			}
			return match.CanonicalMatchID, nil
		}
	}

	// 3. Mint a new canonical id deterministically.
	canonicalID := Mint(pmi.CompetitionID, normHome, normAway, pmi.Kickoff)
	match := CanonicalMatch{
		CanonicalMatchID: canonicalID,
		CompetitionID:    pmi.CompetitionID,
		HomeTeam:         normHome,
		AwayTeam:         normAway,
		Kickoff:          pmi.Kickoff.UTC(),
	}
	alias := MatchAlias{Provider: pmi.Provider, ExternalID: pmi.ExternalID, CanonicalMatchID: canonicalID}
	if err := r.registry.Save(ctx, match, alias); err != nil {
		return uuid.Nil, err
	}
	return canonicalID, nil
}

// Mint deterministically derives a canonical id from the fixture
// attributes. Kickoff is bucketed to the hour so minor cross-provider
// drift within the same hour mints the same id even before the registry
// records an alias; the tolerance-based fuzzy match in Resolve handles
// the cross-hour-boundary cases.
func Mint(competitionID uuid.UUID, normHome, normAway string, kickoff time.Time) uuid.UUID {
	bucket := ""
	if !kickoff.IsZero() {
		bucket = kickoff.UTC().Truncate(time.Hour).Format(time.RFC3339)
	}
	key := strings.Join([]string{competitionID.String(), normHome, normAway, bucket}, "|")
	return uuid.NewSHA1(canonicalNamespace, []byte(key))
}

// Normalize folds a team name to a stable comparison key: lowercase,
// diacritics stripped, non-alphanumerics removed. "Atlético-MG" and
// "Atletico MG" both fold to "atleticomg".
func Normalize(name string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(strings.TrimSpace(name)) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			b.WriteRune(r)
		case unicode.IsLetter(r):
			if folded := foldDiacritic(r); folded != 0 {
				b.WriteRune(folded)
			}
		}
	}
	return b.String()
}

// foldDiacritic maps common Latin accented letters to their ASCII base.
// Covers the accents present in the V1 competitions' team names
// (Portuguese, Spanish, French, etc.). Unknown letters return 0 (dropped).
func foldDiacritic(r rune) rune {
	switch r {
	case 'á', 'à', 'â', 'ã', 'ä', 'å', 'ā':
		return 'a'
	case 'é', 'è', 'ê', 'ë', 'ē':
		return 'e'
	case 'í', 'ì', 'î', 'ï', 'ī':
		return 'i'
	case 'ó', 'ò', 'ô', 'õ', 'ö', 'ō':
		return 'o'
	case 'ú', 'ù', 'û', 'ü', 'ū':
		return 'u'
	case 'ç':
		return 'c'
	case 'ñ':
		return 'n'
	default:
		// Keep other letters that are already ASCII-foldable; drop the
		// rest (rare; never the discriminating token in a team name).
		if r <= unicode.MaxASCII {
			return r
		}
		return 0
	}
}
