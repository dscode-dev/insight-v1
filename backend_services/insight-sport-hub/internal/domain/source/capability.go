// ProviderCapability — provider capability contract.
//
// A static declaration of which data classes each provider adapter can
// currently serve. This is an adapter capability, not a marketing claim
// about the provider's website or paid plans: a field should only be true
// when the adapter actually implements the corresponding fetch path.
//
// Architectural rule: capability checks live behind this type. Code that
// wants to ask "can this provider serve historical odds?" calls Supports
// with the stable SyncType slug instead of branching on provider identity.
package source

// ProviderCapability declares which data classes a provider adapter can
// serve. Boolean per class — additive evolution: new fields are safe because
// the zero value is "unsupported".
type ProviderCapability struct {
	SupportsFixtures           bool
	SupportsHistoricalFixtures bool

	SupportsResults           bool
	SupportsHistoricalResults bool

	SupportsStandings           bool
	SupportsHistoricalStandings bool

	SupportsOdds           bool
	SupportsHistoricalOdds bool

	SupportsPlayers           bool
	SupportsHistoricalPlayers bool

	SupportsLineups           bool
	SupportsHistoricalLineups bool

	SupportsInjuries           bool
	SupportsHistoricalInjuries bool

	SupportsNews bool
}

// Supports returns true iff the named SyncType-style data class is declared on
// this capability set. The string keys mirror the sync.SyncType wire slugs.
//
// Unknown classes return false — strict by design. Future classes need a new
// field on ProviderCapability + a matching case here.
func (c ProviderCapability) Supports(class string) bool {
	switch class {
	case "fixtures":
		return c.SupportsFixtures
	case "historical_fixtures":
		return c.SupportsHistoricalFixtures
	case "results":
		return c.SupportsResults
	case "historical_results":
		return c.SupportsHistoricalResults
	case "standings":
		return c.SupportsStandings
	case "historical_standings":
		return c.SupportsHistoricalStandings
	case "odds":
		return c.SupportsOdds
	case "historical_odds":
		return c.SupportsHistoricalOdds
	case "players":
		return c.SupportsPlayers
	case "historical_players":
		return c.SupportsHistoricalPlayers
	case "lineups":
		return c.SupportsLineups
	case "historical_lineups":
		return c.SupportsHistoricalLineups
	case "injuries":
		return c.SupportsInjuries
	case "historical_injuries":
		return c.SupportsHistoricalInjuries
	case "news":
		return c.SupportsNews
	default:
		return false
	}
}
