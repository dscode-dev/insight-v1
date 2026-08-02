// Mapper coverage for the football_data adapter.
package adapters_test

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/competition"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/football_data"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

const footballDataMatchesBody = `{
  "count":1,
  "filters":{},
  "competition":{"id":2002,"name":"Premier League","code":"PL","type":"LEAGUE"},
  "matches":[
    {
      "id":12345,
      "utcDate":"2026-06-01T19:00:00Z",
      "status":"FINISHED",
      "matchday":15,
      "stage":"REGULAR_SEASON",
      "season":{"id":777,"startDate":"2025-08-15","endDate":"2026-05-30","currentMatchday":15},
      "homeTeam":{"id":1,"name":"Arsenal","shortName":"Arsenal","tla":"ARS"},
      "awayTeam":{"id":2,"name":"Chelsea","shortName":"Chelsea","tla":"CHE"},
      "score":{"winner":"HOME_TEAM","duration":"REGULAR","fullTime":{"home":2,"away":1},"halfTime":{"home":1,"away":0}}
    }
  ]
}`

const footballDataStandingsBody = `{
  "competition":{"id":2002,"name":"Premier League","code":"PL","type":"LEAGUE"},
  "season":{"id":777,"startDate":"2025-08-15","endDate":"2026-05-30","currentMatchday":15},
  "standings":[
    {"stage":"REGULAR_SEASON","type":"TOTAL","group":null,"table":[
      {"position":1,"team":{"id":1,"name":"Arsenal","shortName":"Arsenal","tla":"ARS"},
       "playedGames":15,"form":"WWDWL","won":10,"draw":4,"lost":1,
       "points":34,"goalsFor":28,"goalsAgainst":12,"goalDifference":16}
    ]}
  ]
}`

func TestFootballDataFetchFixturesProducesRawWithFullSourceRef(t *testing.T) {
	srv := newHTTPSrv(t, map[string]string{
		"/competitions/PL/matches": footballDataMatchesBody,
	})
	defer srv.Close()

	registry := competition.NewStrict()
	canon := uuid.MustParse("c1a2b3c4-2222-4222-8222-000000000002")
	_ = registry.Register(context.Background(), ports.Competition{
		ID: canon, Slug: "premier_league",
		Name: "Premier League", CountryCode: "GB", Enabled: true,
	})
	_ = registry.LinkExternalID(context.Background(),
		canon, football_data.SourceID, "PL")

	a := football_data.New(
		football_data.AdapterConfig{
			APIKey:  "test-key",
			BaseURL: srv.URL,
		},
		registry, observability.NewProviderStatus(),
	)

	raws, err := a.FetchFixtures(context.Background(), ports.FixtureFetchRequest{
		CompetitionID: canon,
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(raws) != 1 {
		t.Fatalf("expected 1 raw, got %d", len(raws))
	}
	raw := raws[0]

	// Canonical UUID — provider's numeric id "12345" stays inside
	// the payload, never replaces the canonical key.
	if raw.CompetitionID() != canon {
		t.Errorf("competition uuid lost: %v", raw.CompetitionID())
	}
	if raw.ExternalMatchID() != "12345" {
		t.Errorf("external match id wrong: %q", raw.ExternalMatchID())
	}
	if raw.EventType() != "match.result" {
		t.Errorf("event_type wrong: %q (expected match.result)", raw.EventType())
	}

	// SourceRef full survival.
	ref := raw.Source()
	if ref.SourceID != football_data.SourceID {
		t.Errorf("source_id lost: %q", ref.SourceID)
	}
	if ref.SourceName != football_data.SourceName {
		t.Errorf("source_name lost: %q", ref.SourceName)
	}
	if ref.Type != source.TypeCommercialAPI {
		t.Errorf("source_type lost: %v", ref.Type)
	}
	if ref.AdapterVersion == nil || *ref.AdapterVersion != football_data.AdapterVersion {
		t.Errorf("adapter_version lost: %v", ref.AdapterVersion)
	}
	if ref.Metadata["api_version"] != football_data.APIVersion {
		t.Errorf("metadata.api_version lost: %v", ref.Metadata["api_version"])
	}
}

func TestFootballDataFetchStandingsConsolidatedFromTotalGroup(t *testing.T) {
	srv := newHTTPSrv(t, map[string]string{
		"/competitions/PL/standings": footballDataStandingsBody,
	})
	defer srv.Close()

	registry := competition.NewStrict()
	canon := uuid.New()
	_ = registry.Register(context.Background(), ports.Competition{
		ID: canon, Slug: "pl-test", Name: "PL test", CountryCode: "GB", Enabled: true,
	})
	_ = registry.LinkExternalID(context.Background(),
		canon, football_data.SourceID, "PL")

	a := football_data.New(
		football_data.AdapterConfig{APIKey: "test-key", BaseURL: srv.URL},
		registry, observability.NewProviderStatus(),
	)

	raws, err := a.FetchStandings(context.Background(), ports.StandingsFetchRequest{
		CompetitionID: canon,
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(raws) != 1 {
		t.Fatalf("expected 1 standings raw, got %d", len(raws))
	}
	if raws[0].EventType() != "competition.standings" {
		t.Errorf("wrong event_type: %q", raws[0].EventType())
	}
	if raws[0].Payload()["row_count"].(int) != 1 {
		t.Errorf("row_count wrong: %v", raws[0].Payload()["row_count"])
	}
}
