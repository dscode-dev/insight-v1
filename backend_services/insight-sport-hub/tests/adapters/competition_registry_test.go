// CompetitionRegistry (in-memory variant) — exercises the full
// Sprint 2 interface: register, lookup, link external id, reverse
// lookup, enable/disable, list.
//
// The Postgres adapter is tested separately by integration tests
// (deferred to a follow-up sprint when a real DB fixture lands).
// In-memory + Postgres share the same port contract, so identical
// behavioural tests apply.
package adapters_test

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/competition"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

func TestCompetitionRegisterAndLookup(t *testing.T) {
	r := competition.NewStrict()
	id := uuid.New()
	c := ports.Competition{
		ID: id, Slug: "test", Name: "Test", CountryCode: "BR", Enabled: true,
	}
	if err := r.Register(context.Background(), c); err != nil {
		t.Fatalf("register: %v", err)
	}
	got, err := r.Lookup(context.Background(), id)
	if err != nil {
		t.Fatalf("lookup: %v", err)
	}
	if got.Slug != "test" || !got.Enabled {
		t.Errorf("unexpected lookup result: %+v", got)
	}
}

func TestCompetitionLinkAndReverseLookup(t *testing.T) {
	r := competition.NewStrict()
	canonical := uuid.New()
	_ = r.Register(context.Background(), ports.Competition{
		ID: canonical, Slug: "x", Name: "X", CountryCode: "XX", Enabled: true,
	})
	if err := r.LinkExternalID(
		context.Background(), canonical, "api_football", "71",
	); err != nil {
		t.Fatalf("link: %v", err)
	}

	// Forward: provider → canonical
	got, err := r.LookupByExternalID(context.Background(), "api_football", "71")
	if err != nil {
		t.Fatalf("forward lookup: %v", err)
	}
	if got.ID != canonical {
		t.Errorf("forward lookup mismatch: got %v", got.ID)
	}

	// Reverse: canonical → provider
	ext, err := r.GetExternalIDForSource(context.Background(), canonical, "api_football")
	if err != nil {
		t.Fatalf("reverse lookup: %v", err)
	}
	if ext != "71" {
		t.Errorf("reverse lookup wrong: %q", ext)
	}
}

func TestCompetitionReverseLookupReturnsNotFoundForUnknownPair(t *testing.T) {
	r := competition.NewStrict()
	_, err := r.GetExternalIDForSource(context.Background(), uuid.New(), "api_football")
	if !errors.Is(err, ports.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestCompetitionIsKnownRespectsEnabledFlag(t *testing.T) {
	r := competition.NewStrict()
	id := uuid.New()
	_ = r.Register(context.Background(), ports.Competition{
		ID: id, Slug: "x", Name: "X", CountryCode: "XX", Enabled: true,
	})
	known, _ := r.IsKnown(context.Background(), id)
	if !known {
		t.Error("expected enabled competition to be known")
	}
	_ = r.SetEnabled(context.Background(), id, false)
	known, _ = r.IsKnown(context.Background(), id)
	if known {
		t.Error("disabled competition should NOT be known")
	}
}

func TestCompetitionPermissiveModeForSprint1Compat(t *testing.T) {
	r := competition.New() // permissive
	known, err := r.IsKnown(context.Background(), uuid.New())
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if !known {
		t.Error("permissive empty registry should accept any id")
	}
}
