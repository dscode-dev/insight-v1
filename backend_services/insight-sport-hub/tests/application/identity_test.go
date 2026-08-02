// Cross-provider match identity — Sprint 6.2.
package application_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/application/identity"
)

var idComp = uuid.MustParse("44444444-4444-4444-8444-444444444444")

func pmi(provider, ext, home, away string, kickoff time.Time) identity.ProviderMatchIdentity {
	return identity.ProviderMatchIdentity{
		Provider: provider, ExternalID: ext, CompetitionID: idComp,
		HomeTeam: home, AwayTeam: away, Kickoff: kickoff,
	}
}

func TestIdentityNormalizeFoldsAccentsAndPunctuation(t *testing.T) {
	if got := identity.Normalize("Atlético-MG"); got != "atleticomg" {
		t.Errorf("normalize: got %q", got)
	}
	if identity.Normalize("Grêmio") != "gremio" {
		t.Errorf("diacritic fold failed: %q", identity.Normalize("Grêmio"))
	}
	if identity.Normalize("  Real  Madrid  ") != "realmadrid" {
		t.Errorf("space strip failed")
	}
}

func TestIdentityDeterministicMint(t *testing.T) {
	k := time.Date(2026, 6, 1, 19, 0, 0, 0, time.UTC)
	a := identity.Mint(idComp, "brazil", "argentina", k)
	b := identity.Mint(idComp, "brazil", "argentina", k)
	if a != b {
		t.Error("mint must be deterministic for identical inputs")
	}
	if a == identity.Mint(idComp, "brazil", "chile", k) {
		t.Error("different away team must mint a different id")
	}
}

func TestIdentityResolveSameAliasReturnsSame(t *testing.T) {
	r := identity.NewResolver(identity.NewMemoryRegistry(), 90*time.Minute)
	ctx := context.Background()
	k := time.Date(2026, 6, 1, 19, 0, 0, 0, time.UTC)

	id1, err := r.Resolve(ctx, pmi("api_football", "F1", "Brazil", "Argentina", k))
	if err != nil {
		t.Fatal(err)
	}
	// Same provider + external id → alias hit → same canonical id.
	id2, _ := r.Resolve(ctx, pmi("api_football", "F1", "Brazil", "Argentina", k))
	if id1 != id2 {
		t.Error("alias lookup must return the same canonical id")
	}
}

func TestIdentityResolveCrossProviderUnifies(t *testing.T) {
	r := identity.NewResolver(identity.NewMemoryRegistry(), 90*time.Minute)
	ctx := context.Background()
	k := time.Date(2026, 6, 1, 19, 0, 0, 0, time.UTC)

	apiFootball, _ := r.Resolve(ctx, pmi("api_football", "F1", "Brazil", "Argentina", k))
	// Different provider, different external id, kickoff drifted 20 min,
	// same teams + competition → fuzzy match → SAME canonical id.
	theOdds, _ := r.Resolve(ctx, pmi("the_odds_api", "ODDS_9", "Brazil", "Argentina", k.Add(20*time.Minute)))
	if apiFootball != theOdds {
		t.Errorf("the same fixture across providers must unify: %v vs %v", apiFootball, theOdds)
	}
}

func TestIdentityResolveBeyondToleranceDoesNotMerge(t *testing.T) {
	r := identity.NewResolver(identity.NewMemoryRegistry(), 90*time.Minute)
	ctx := context.Background()
	k := time.Date(2026, 6, 1, 19, 0, 0, 0, time.UTC)

	first, _ := r.Resolve(ctx, pmi("api_football", "F1", "Brazil", "Argentina", k))
	// 5 hours later = a DIFFERENT fixture (e.g. a rematch) — must not merge.
	second, _ := r.Resolve(ctx, pmi("football_data", "FD_2", "Brazil", "Argentina", k.Add(5*time.Hour)))
	if first == second {
		t.Error("fixtures outside the kickoff tolerance must not merge")
	}
}

func TestIdentityResolvePreservesAliases(t *testing.T) {
	reg := identity.NewMemoryRegistry()
	r := identity.NewResolver(reg, 90*time.Minute)
	ctx := context.Background()
	k := time.Date(2026, 6, 1, 19, 0, 0, 0, time.UTC)

	id, _ := r.Resolve(ctx, pmi("the_odds_api", "ODDS_9", "Brazil", "Argentina", k))
	got, ok, err := reg.AliasLookup(ctx, "the_odds_api", "ODDS_9")
	if err != nil || !ok || got != id {
		t.Errorf("provider id must be preserved as an alias: ok=%v got=%v", ok, got)
	}
}
