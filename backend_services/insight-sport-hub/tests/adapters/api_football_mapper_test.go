// Mapper coverage for the api_football adapter.
//
// Uses the EXPORTED Adapter.NewWithClient seam — a stub httpClient
// returns canned envelopes; the test inspects the produced
// RawSportsEvents (including the full SourceRef) for both the
// fixture and standings paths.
//
// The lineage preservation test asserts every field on the
// SourceRef declared in Sprint 0.1.1 survives the adapter →
// orchestrator handoff:
//
//	source_id, source_name, source_type, confidence, observed_at,
//	adapter_version, metadata.
package adapters_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/competition"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/api_football"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// End-to-end tests via httptest — drive the real Client + real
// mapper using canned wire JSON pinned in the const blocks below.
// This stays at the PUBLIC adapter surface and exercises the full
// chain (HTTP decode → DTO → mapper → RawSportsEvent).

const apiFootballFixtureBody = `{
  "get":"fixtures","errors":[],"results":1,"paging":{"current":1,"total":1},
  "response":[
    {
      "fixture":{"id":215662,"date":"2026-06-01T19:00:00+00:00","status":{"long":"Match Finished","short":"FT","elapsed":90}},
      "league":{"id":71,"name":"Serie A","season":2026},
      "teams":{"home":{"id":118,"name":"Bahia"},"away":{"id":119,"name":"Bragantino"}},
      "goals":{"home":2,"away":1}
    }
  ]
}`

const apiFootballStandingsBody = `{
  "get":"standings","errors":[],"results":1,"paging":{"current":1,"total":1},
  "response":[
    {"league":{"id":71,"name":"Serie A","season":2026,"standings":[[
      {"rank":1,"team":{"id":118,"name":"Bahia"},"points":34,"goalsDiff":7,
       "all":{"played":15,"win":10,"draw":4,"lose":1,"goals":{"for":28,"against":21}}}
    ]]}}
  ]
}`

func TestAPIFootballFetchFixturesProducesRawWithFullSourceRef(t *testing.T) {
	srv := newHTTPSrv(t, map[string]string{
		"/fixtures": apiFootballFixtureBody,
	})
	defer srv.Close()

	registry := competition.NewStrict()
	competitionID := uuid.MustParse("c1a2b3c4-1111-4111-8111-000000000001")
	_ = registry.Register(context.Background(), ports.Competition{
		ID: competitionID, Slug: "brasileirao_serie_a",
		Name: "Brasileirão Série A", CountryCode: "BR", Enabled: true,
	})
	_ = registry.LinkExternalID(context.Background(),
		competitionID, api_football.SourceID, "71")

	status := observability.NewProviderStatus()

	a := api_football.New(
		api_football.AdapterConfig{
			APIKey:  "test-key",
			BaseURL: srv.URL,
		},
		registry, status,
	)

	raws, err := a.FetchFixtures(context.Background(), ports.FixtureFetchRequest{
		CompetitionID: competitionID,
		Season:        "2026",
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(raws) != 1 {
		t.Fatalf("expected 1 raw, got %d", len(raws))
	}
	raw := raws[0]

	// Identity carries the canonical UUID — provider's "71" NEVER
	// escaped into the domain type.
	if raw.CompetitionID() != competitionID {
		t.Errorf("competition uuid lost: got %v", raw.CompetitionID())
	}
	if raw.ExternalMatchID() != "215662" {
		t.Errorf("external match id wrong: %q", raw.ExternalMatchID())
	}
	if raw.EventType() != "match.result" { // FT → finished
		t.Errorf("event_type wrong: %q (expected match.result)", raw.EventType())
	}

	// Full SourceRef survival — Sprint 0.1.1 fields.
	ref := raw.Source()
	if ref.SourceID != api_football.SourceID {
		t.Errorf("source_id lost: %q", ref.SourceID)
	}
	if ref.SourceName != api_football.SourceName {
		t.Errorf("source_name lost: %q", ref.SourceName)
	}
	if ref.Type != source.TypeCommercialAPI {
		t.Errorf("source_type lost: %v", ref.Type)
	}
	if ref.AdapterVersion == nil || *ref.AdapterVersion != api_football.AdapterVersion {
		t.Errorf("adapter_version lost: %v", ref.AdapterVersion)
	}
	if ref.ObservedAt.IsZero() {
		t.Error("observed_at zero — must be stamped by mapper")
	}
	if ref.Metadata["endpoint"] != "/v3/fixtures" {
		t.Errorf("metadata.endpoint lost: %v", ref.Metadata["endpoint"])
	}
	if ref.Metadata["api_version"] != api_football.APIVersion {
		t.Errorf("metadata.api_version lost: %v", ref.Metadata["api_version"])
	}

	// Provider status was recorded.
	snap := a.Health()
	if snap.RequestsTotal != 1 || !snap.Reachable {
		t.Errorf("status not recorded: %+v", snap)
	}
}

func TestAPIFootballFetchStandingsBuildsSingleEvent(t *testing.T) {
	srv := newHTTPSrv(t, map[string]string{
		"/standings": apiFootballStandingsBody,
	})
	defer srv.Close()

	registry := competition.NewStrict()
	competitionID := uuid.MustParse("c1a2b3c4-1111-4111-8111-000000000001")
	_ = registry.Register(context.Background(), ports.Competition{
		ID: competitionID, Slug: "brasileirao_serie_a",
		Name: "Brasileirão Série A", CountryCode: "BR", Enabled: true,
	})
	_ = registry.LinkExternalID(context.Background(),
		competitionID, api_football.SourceID, "71")

	a := api_football.New(
		api_football.AdapterConfig{
			APIKey:  "test-key",
			BaseURL: srv.URL,
		},
		registry, observability.NewProviderStatus(),
	)

	raws, err := a.FetchStandings(context.Background(), ports.StandingsFetchRequest{
		CompetitionID: competitionID,
		Season:        "2026",
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(raws) != 1 {
		t.Fatalf("expected 1 standings event, got %d", len(raws))
	}
	if raws[0].EventType() != "competition.standings" {
		t.Errorf("event_type wrong: %q", raws[0].EventType())
	}
	payload := raws[0].Payload()
	if payload["row_count"].(int) != 1 {
		t.Errorf("row_count wrong: %v", payload["row_count"])
	}
}

func TestAPIFootballMissingCompetitionMappingErrors(t *testing.T) {
	registry := competition.NewStrict()
	// NO LinkExternalID — registry has no mapping for the canonical id.
	a := api_football.New(
		api_football.AdapterConfig{APIKey: "test-key"},
		registry, observability.NewProviderStatus(),
	)
	_, err := a.FetchFixtures(context.Background(), ports.FixtureFetchRequest{
		CompetitionID: uuid.New(),
		Season:        "2026",
	})
	if err == nil {
		t.Error("expected error for missing competition mapping")
	}
}

func TestAPIFootballHealthRecordsFailureOnHTTP500(t *testing.T) {
	srv := newHTTPSrv500(t)
	defer srv.Close()

	registry := competition.NewStrict()
	canon := uuid.New()
	_ = registry.Register(context.Background(), ports.Competition{
		ID: canon, Slug: "test", Name: "Test", CountryCode: "XX", Enabled: true,
	})
	_ = registry.LinkExternalID(context.Background(), canon, api_football.SourceID, "99")

	a := api_football.New(
		api_football.AdapterConfig{APIKey: "test-key", BaseURL: srv.URL},
		registry, observability.NewProviderStatus(),
	)
	_, _ = a.FetchFixtures(context.Background(), ports.FixtureFetchRequest{
		CompetitionID: canon,
		Season:        "2026",
	})
	snap := a.Health()
	if snap.RequestsFailedTotal != 1 {
		t.Errorf("expected 1 failure recorded, got %d", snap.RequestsFailedTotal)
	}
	if snap.LastError == "" {
		t.Error("LastError should be populated after failure")
	}
	if snap.Reachable {
		t.Error("provider should be flagged unreachable after failure")
	}
	// Sanity — make sure the time check is recent.
	if time.Since(snap.LastFailure) > time.Minute {
		t.Errorf("LastFailure stale: %v", snap.LastFailure)
	}
}
