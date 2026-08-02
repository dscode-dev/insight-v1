// ProviderCapability contract.
package domain_test

import (
	"testing"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
)

func TestProviderCapabilitySupportsReturnsField(t *testing.T) {
	c := source.ProviderCapability{
		SupportsFixtures:            true,
		SupportsHistoricalFixtures:  false,
		SupportsResults:             true,
		SupportsHistoricalResults:   false,
		SupportsStandings:           true,
		SupportsHistoricalStandings: false,
		SupportsOdds:                true,
		SupportsHistoricalOdds:      false,
		SupportsPlayers:             true,
		SupportsHistoricalPlayers:   false,
		SupportsLineups:             true,
		SupportsHistoricalLineups:   false,
		SupportsInjuries:            true,
		SupportsHistoricalInjuries:  false,
		SupportsNews:                true,
	}
	cases := map[string]bool{
		"fixtures":             true,
		"historical_fixtures":  false,
		"results":              true,
		"historical_results":   false,
		"standings":            true,
		"historical_standings": false,
		"odds":                 true,
		"historical_odds":      false,
		"players":              true,
		"historical_players":   false,
		"lineups":              true,
		"historical_lineups":   false,
		"injuries":             true,
		"historical_injuries":  false,
		"news":                 true,
	}
	for class, expected := range cases {
		if got := c.Supports(class); got != expected {
			t.Errorf("Supports(%q) = %v, want %v", class, got, expected)
		}
	}
}

func TestProviderCapabilityUnknownClassReturnsFalse(t *testing.T) {
	c := source.ProviderCapability{
		SupportsFixtures: true, SupportsHistoricalFixtures: true,
		SupportsResults: true, SupportsHistoricalResults: true,
		SupportsStandings: true, SupportsHistoricalStandings: true,
		SupportsOdds: true, SupportsHistoricalOdds: true,
		SupportsPlayers: true, SupportsHistoricalPlayers: true,
		SupportsLineups: true, SupportsHistoricalLineups: true,
		SupportsInjuries: true, SupportsHistoricalInjuries: true,
		SupportsNews: true,
	}
	if c.Supports("commentary") {
		t.Error("unknown class must return false even when every known class is enabled")
	}
}

func TestProviderCapabilityZeroValueSupportsNothing(t *testing.T) {
	var c source.ProviderCapability
	for _, class := range []string{
		"fixtures", "historical_fixtures",
		"results", "historical_results",
		"standings", "historical_standings",
		"odds", "historical_odds",
		"players", "historical_players",
		"lineups", "historical_lineups",
		"injuries", "historical_injuries",
		"news",
	} {
		if c.Supports(class) {
			t.Errorf("zero value must NOT support %q", class)
		}
	}
}
