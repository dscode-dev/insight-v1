// Mapper + adapter coverage for the the_odds_api provider.
//
// Drives the real Client + real mapper through an httptest server
// serving canned v4 wire JSON, then inspects the produced
// match.odds RawSportsEvents — including the full SourceRef and the
// history-preservation invariant (one raw per bookmaker×market, each
// with a snapshot-unique external_match_id).
package adapters_test

import (
	"context"
	"testing"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/competition"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/the_odds_api"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

const theOddsAPIBody = `[
  {
    "id":"e912304de2b2ce35b1a92a51474f9e26",
    "sport_key":"soccer_epl",
    "sport_title":"EPL",
    "commence_time":"2026-06-01T14:00:00Z",
    "home_team":"Chelsea",
    "away_team":"Burnley",
    "bookmakers":[
      {
        "key":"bet365","title":"Bet365","last_update":"2026-06-01T10:00:00Z",
        "markets":[
          {"key":"h2h","last_update":"2026-06-01T10:00:00Z","outcomes":[
            {"name":"Chelsea","price":1.83},
            {"name":"Burnley","price":4.75},
            {"name":"Draw","price":3.40}
          ]}
        ]
      },
      {
        "key":"pinnacle","title":"Pinnacle","last_update":"2026-06-01T10:01:00Z",
        "markets":[
          {"key":"h2h","last_update":"2026-06-01T10:01:00Z","outcomes":[
            {"name":"Chelsea","price":1.80},
            {"name":"Burnley","price":4.90},
            {"name":"Draw","price":3.50}
          ]}
        ]
      }
    ]
  }
]`

func TestTheOddsAPIFetchOddsProducesCanonicalOddsRaws(t *testing.T) {
	srv := newHTTPSrv(t, map[string]string{
		"/v4/sports/soccer_epl/odds": theOddsAPIBody,
	})
	defer srv.Close()

	registry := competition.NewStrict()
	competitionID := uuid.MustParse("c1a2b3c4-1111-4111-8111-000000000009")
	_ = registry.Register(context.Background(), ports.Competition{
		ID: competitionID, Slug: "epl", Name: "Premier League",
		CountryCode: "GB", Enabled: true,
	})
	_ = registry.LinkExternalID(context.Background(),
		competitionID, the_odds_api.SourceID, "soccer_epl")

	status := observability.NewProviderStatus()
	a := the_odds_api.New(
		the_odds_api.AdapterConfig{APIKey: "test-key", BaseURL: srv.URL},
		registry, status,
	)

	raws, err := a.FetchOdds(context.Background(), ports.OddsFetchRequest{
		CompetitionID: competitionID,
		Markets:       []string{"h2h"},
		Regions:       []string{"eu"},
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	// One raw per bookmaker×market (2 bookmakers, 1 market each).
	if len(raws) != 2 {
		t.Fatalf("expected 2 odds raws, got %d", len(raws))
	}

	seenExternal := map[string]bool{}
	seenMatchID := map[string]bool{}
	for _, raw := range raws {
		if raw.EventType() != "match.odds" {
			t.Errorf("event_type wrong: %q (want match.odds)", raw.EventType())
		}
		if raw.CompetitionID() != competitionID {
			t.Errorf("competition uuid lost: %v", raw.CompetitionID())
		}
		// Snapshot-unique external id → distinct canonical identities
		// → history preserved per snapshot.
		if seenExternal[raw.ExternalMatchID()] {
			t.Errorf("external_match_id collision: %q", raw.ExternalMatchID())
		}
		seenExternal[raw.ExternalMatchID()] = true

		p := raw.Payload()
		if p["provider"] != the_odds_api.SourceID {
			t.Errorf("payload provider wrong: %v", p["provider"])
		}
		if p["market"] != "h2h" {
			t.Errorf("payload market wrong: %v", p["market"])
		}
		// Stable per-match grouping key — identical across bookmakers.
		mid, _ := p["match_id"].(string)
		if mid == "" {
			t.Errorf("payload match_id missing")
		}
		seenMatchID[mid] = true
		if _, ok := p["captured_at"]; !ok {
			t.Errorf("payload captured_at missing")
		}

		// Full SourceRef survival.
		ref := raw.Source()
		if ref.SourceID != the_odds_api.SourceID {
			t.Errorf("source_id lost: %q", ref.SourceID)
		}
		if ref.AdapterVersion == nil || *ref.AdapterVersion != the_odds_api.AdapterVersion {
			t.Errorf("adapter_version lost: %v", ref.AdapterVersion)
		}
		if ref.Type != source.TypeCommercialAPI {
			t.Errorf("source_type lost: %v", ref.Type)
		}
		if ref.Metadata["api_version"] != the_odds_api.APIVersion {
			t.Errorf("metadata.api_version lost: %v", ref.Metadata["api_version"])
		}
	}

	// All bookmakers for one provider event share ONE stable match_id.
	if len(seenMatchID) != 1 {
		t.Errorf("expected one stable match_id across bookmakers, got %d", len(seenMatchID))
	}

	// h2h home/draw/away surfaced as numeric top-level fields.
	bet365 := findRawByBookmaker(t, raws, "bet365")
	if got := bet365.Payload()["home"]; got != 1.83 {
		t.Errorf("home odds wrong: %v (want 1.83)", got)
	}
	if got := bet365.Payload()["draw"]; got != 3.40 {
		t.Errorf("draw odds wrong: %v (want 3.40)", got)
	}
	if got := bet365.Payload()["away"]; got != 4.75 {
		t.Errorf("away odds wrong: %v (want 4.75)", got)
	}

	snap := a.Health()
	if snap.RequestsTotal != 1 || !snap.Reachable {
		t.Errorf("status not recorded: %+v", snap)
	}
}

func TestTheOddsAPICapabilitiesOnlyOdds(t *testing.T) {
	caps := the_odds_api.Capabilities()
	if !caps.SupportsOdds || !caps.SupportsHistoricalOdds {
		t.Errorf("odds capabilities must be true: %+v", caps)
	}
	if caps.SupportsFixtures || caps.SupportsResults || caps.SupportsStandings ||
		caps.SupportsPlayers || caps.SupportsLineups || caps.SupportsInjuries ||
		caps.SupportsNews {
		t.Errorf("non-odds capabilities must be false: %+v", caps)
	}
}

func findRawByBookmaker(t *testing.T, raws []*event.RawSportsEvent, key string) *event.RawSportsEvent {
	t.Helper()
	for _, r := range raws {
		if r.Payload()["bookmaker"] == key {
			return r
		}
	}
	t.Fatalf("no raw for bookmaker %q", key)
	return nil
}
