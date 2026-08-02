// Package sync — architectural contracts for the Scheduler/Sync Engine.
package sync

import (
	"errors"
	"fmt"
)

// SyncType — the data class one SyncJob refreshes. Values are stable wire
// identifiers used by admin tooling, status endpoints, and future stream keys.
type SyncType string

const (
	TypeFixtures           SyncType = "fixtures"
	TypeHistoricalFixtures SyncType = "historical_fixtures"

	TypeResults           SyncType = "results"
	TypeHistoricalResults SyncType = "historical_results"

	TypeStandings           SyncType = "standings"
	TypeHistoricalStandings SyncType = "historical_standings"

	TypeOdds           SyncType = "odds"
	TypeHistoricalOdds SyncType = "historical_odds"

	TypePlayers           SyncType = "players"
	TypeHistoricalPlayers SyncType = "historical_players"

	TypeLineups           SyncType = "lineups"
	TypeHistoricalLineups SyncType = "historical_lineups"

	TypeInjuries           SyncType = "injuries"
	TypeHistoricalInjuries SyncType = "historical_injuries"

	TypeNews SyncType = "news"
)

var ErrUnknownSyncType = errors.New("sync: unknown sync_type")

// ParseSyncType validates a wire string and returns the typed value.
func ParseSyncType(s string) (SyncType, error) {
	switch SyncType(s) {
	case TypeFixtures, TypeHistoricalFixtures,
		TypeResults, TypeHistoricalResults,
		TypeStandings, TypeHistoricalStandings,
		TypeOdds, TypeHistoricalOdds,
		TypePlayers, TypeHistoricalPlayers,
		TypeLineups, TypeHistoricalLineups,
		TypeInjuries, TypeHistoricalInjuries,
		TypeNews:
		return SyncType(s), nil
	default:
		return "", fmt.Errorf("%w: %q", ErrUnknownSyncType, s)
	}
}

// All — every defined SyncType in stable display order. Additive-only.
func All() []SyncType {
	return []SyncType{
		TypeFixtures, TypeHistoricalFixtures,
		TypeResults, TypeHistoricalResults,
		TypeStandings, TypeHistoricalStandings,
		TypeOdds, TypeHistoricalOdds,
		TypePlayers, TypeHistoricalPlayers,
		TypeLineups, TypeHistoricalLineups,
		TypeInjuries, TypeHistoricalInjuries,
		TypeNews,
	}
}
