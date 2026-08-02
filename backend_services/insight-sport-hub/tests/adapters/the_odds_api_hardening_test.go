// Sprint 6.1 the_odds_api hardening — cache request-collapsing, budget
// recording on real fetches only, and outcomes preservation for
// non-h2h markets.
package adapters_test

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/competition"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/the_odds_api"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

const theOddsAPITotalsBody = `[
  {
    "id":"ev_totals_1","sport_key":"soccer_epl","sport_title":"EPL",
    "commence_time":"2026-06-01T14:00:00Z","home_team":"Chelsea","away_team":"Burnley",
    "bookmakers":[
      {"key":"bet365","title":"Bet365","last_update":"2026-06-01T10:00:00Z","markets":[
        {"key":"totals","last_update":"2026-06-01T10:00:00Z","outcomes":[
          {"name":"Over","price":1.90,"point":2.5},
          {"name":"Under","price":1.90,"point":2.5}
        ]}
      ]}
    ]
  }
]`

func newOddsRegistry(t *testing.T) (ports.CompetitionRegistry, uuid.UUID) {
	t.Helper()
	registry := competition.NewStrict()
	competitionID := uuid.MustParse("c1a2b3c4-1111-4111-8111-0000000000aa")
	_ = registry.Register(context.Background(), ports.Competition{
		ID: competitionID, Slug: "epl", Name: "Premier League", CountryCode: "GB", Enabled: true,
	})
	_ = registry.LinkExternalID(context.Background(), competitionID, the_odds_api.SourceID, "soccer_epl")
	return registry, competitionID
}

// fakeCache records loader invocations and serves a memoised value.
type fakeCache struct {
	loads atomic.Int64
	val   []byte
	has   bool
}

func (c *fakeCache) Fetch(ctx context.Context, _ string, loader func(context.Context) ([]byte, error)) ([]byte, error) {
	if c.has {
		return c.val, nil
	}
	c.loads.Add(1)
	b, err := loader(ctx)
	if err != nil {
		return nil, err
	}
	c.val = b
	c.has = true
	return b, nil
}

type countingRecorder struct{ n atomic.Int64 }

func (r *countingRecorder) RecordRequest(_ context.Context, _ string) { r.n.Add(1) }

func TestTheOddsAPIPreservesNonH2HOutcomes(t *testing.T) {
	srv := newHTTPSrv(t, map[string]string{"/v4/sports/soccer_epl/odds": theOddsAPITotalsBody})
	defer srv.Close()
	registry, competitionID := newOddsRegistry(t)

	a := the_odds_api.New(
		the_odds_api.AdapterConfig{APIKey: "k", BaseURL: srv.URL}, registry, observability.NewProviderStatus(),
	)
	raws, err := a.FetchOdds(context.Background(), ports.OddsFetchRequest{CompetitionID: competitionID, Markets: []string{"totals"}})
	if err != nil {
		t.Fatalf("fetch: %v", err)
	}
	if len(raws) != 1 {
		t.Fatalf("expected 1 totals raw, got %d", len(raws))
	}
	p := raws[0].Payload()
	if p["market"] != "totals" {
		t.Errorf("market wrong: %v", p["market"])
	}
	// h2h convenience fields must be ABSENT for a non-h2h market.
	if _, ok := p["home"]; ok {
		t.Error("home must not be set for non-h2h markets")
	}
	// outcomes[] is the source of truth and must be preserved in full.
	outcomes, ok := p["outcomes"].([]map[string]any)
	if !ok || len(outcomes) != 2 {
		t.Fatalf("outcomes not preserved: %#v", p["outcomes"])
	}
	if outcomes[0]["point"] != 2.5 {
		t.Errorf("outcome point (asian/totals line) lost: %#v", outcomes[0])
	}
}

func TestTheOddsAPICacheHitAvoidsAPIAndBudget(t *testing.T) {
	srv := newHTTPSrv(t, map[string]string{"/v4/sports/soccer_epl/odds": theOddsAPIBody})
	defer srv.Close()
	registry, competitionID := newOddsRegistry(t)

	cache := &fakeCache{}
	rec := &countingRecorder{}
	a := the_odds_api.New(
		the_odds_api.AdapterConfig{APIKey: "k", BaseURL: srv.URL}, registry, observability.NewProviderStatus(),
		the_odds_api.WithCache(cache), the_odds_api.WithRequestRecorder(rec),
	)
	req := ports.OddsFetchRequest{CompetitionID: competitionID, Markets: []string{"h2h"}}

	// First fetch: cache miss → loader runs → 1 API call + 1 budget record.
	if _, err := a.FetchOdds(context.Background(), req); err != nil {
		t.Fatalf("fetch 1: %v", err)
	}
	// Second + third fetch: cache hit → no loader, no API call, no budget spend.
	if _, err := a.FetchOdds(context.Background(), req); err != nil {
		t.Fatalf("fetch 2: %v", err)
	}
	if _, err := a.FetchOdds(context.Background(), req); err != nil {
		t.Fatalf("fetch 3: %v", err)
	}

	if cache.loads.Load() != 1 {
		t.Errorf("loader should run once (cache miss), ran %d", cache.loads.Load())
	}
	if rec.n.Load() != 1 {
		t.Errorf("budget should be recorded once (real fetch only), got %d", rec.n.Load())
	}
}

// observerSpy records kickoff feeds.
type observerSpy struct{ kicks atomic.Int64 }

func (o *observerSpy) ObserveKickoff(_ context.Context, _ uuid.UUID, _ string, k time.Time) {
	if !k.IsZero() {
		o.kicks.Add(1)
	}
}

func TestTheOddsAPIFeedsKickoffObserver(t *testing.T) {
	srv := newHTTPSrv(t, map[string]string{"/v4/sports/soccer_epl/odds": theOddsAPIBody})
	defer srv.Close()
	registry, competitionID := newOddsRegistry(t)

	spy := &observerSpy{}
	a := the_odds_api.New(
		the_odds_api.AdapterConfig{APIKey: "k", BaseURL: srv.URL}, registry, observability.NewProviderStatus(),
		the_odds_api.WithScheduleObserver(spy),
	)
	if _, err := a.FetchOdds(context.Background(), ports.OddsFetchRequest{CompetitionID: competitionID}); err != nil {
		t.Fatalf("fetch: %v", err)
	}
	if spy.kicks.Load() == 0 {
		t.Error("adapter must feed the kickoff observer with commence_time")
	}
}
