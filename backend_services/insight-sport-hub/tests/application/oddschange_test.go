// Odds change-detection publish gate — Sprint 6.1 stream denoising.
package application_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/application/oddschange"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

var oddsMatchID = uuid.MustParse("11111111-1111-4111-8111-111111111111")
var oddsCompID = uuid.MustParse("22222222-2222-4222-8222-222222222222")

func oddsCanonical(t *testing.T, home, draw, away float64) *event.CanonicalSportsEvent {
	t.Helper()
	now := time.Now().UTC()
	payload := map[string]any{
		"provider":  "the_odds_api",
		"match_id":  oddsMatchID.String(),
		"market":    "h2h",
		"bookmaker": "bet365",
		"home":      home,
		"draw":      draw,
		"away":      away,
		"outcomes": []map[string]any{
			{"name": "Chelsea", "price": home},
			{"name": "Burnley", "price": away},
			{"name": "Draw", "price": draw},
		},
	}
	ref := source.SourceRef{SourceID: "the_odds_api", ObservedAt: now, Confidence: 0.8}
	c, err := event.NewCanonical(
		uuid.New(),
		event.Identity{Sport: sport.Football, CompetitionID: oddsCompID, MatchID: oddsMatchID, EventType: "match.odds"},
		"", now, payload, []source.SourceRef{ref}, 0.8,
	)
	if err != nil {
		t.Fatalf("build canonical: %v", err)
	}
	return c
}

func TestGateFirstSnapshotPublishes(t *testing.T) {
	gate := oddschange.NewGate(0.5, oddschange.NewMemoryStore(), time.Hour)
	ok, err := gate.ShouldPublish(context.Background(), oddsCanonical(t, 1.83, 3.40, 4.75))
	if err != nil || !ok {
		t.Fatalf("first snapshot must publish: ok=%v err=%v", ok, err)
	}
}

func TestGateSuppressesUnchanged(t *testing.T) {
	gate := oddschange.NewGate(0.5, oddschange.NewMemoryStore(), time.Hour)
	ctx := context.Background()
	if ok, _ := gate.ShouldPublish(ctx, oddsCanonical(t, 1.83, 3.40, 4.75)); !ok {
		t.Fatal("first must publish")
	}
	if ok, _ := gate.ShouldPublish(ctx, oddsCanonical(t, 1.83, 3.40, 4.75)); ok {
		t.Error("identical snapshot must be suppressed")
	}
}

func TestGateSuppressesSubThreshold(t *testing.T) {
	gate := oddschange.NewGate(0.5, oddschange.NewMemoryStore(), time.Hour)
	ctx := context.Background()
	gate.ShouldPublish(ctx, oddsCanonical(t, 1.830, 3.40, 4.75))
	// ~0.05% move on home — below the 0.5% threshold.
	if ok, _ := gate.ShouldPublish(ctx, oddsCanonical(t, 1.831, 3.40, 4.75)); ok {
		t.Error("sub-threshold move must be suppressed")
	}
}

func TestGatePublishesMeaningfulMove(t *testing.T) {
	gate := oddschange.NewGate(0.5, oddschange.NewMemoryStore(), time.Hour)
	ctx := context.Background()
	gate.ShouldPublish(ctx, oddsCanonical(t, 1.83, 3.40, 4.75))
	// ~3.8% move on home — well above threshold.
	if ok, _ := gate.ShouldPublish(ctx, oddsCanonical(t, 1.90, 3.40, 4.75)); !ok {
		t.Error("meaningful move must publish")
	}
}

func TestGateZeroThresholdPublishesEverything(t *testing.T) {
	gate := oddschange.NewGate(0, oddschange.NewMemoryStore(), time.Hour)
	ctx := context.Background()
	gate.ShouldPublish(ctx, oddsCanonical(t, 1.83, 3.40, 4.75))
	if ok, _ := gate.ShouldPublish(ctx, oddsCanonical(t, 1.83, 3.40, 4.75)); !ok {
		t.Error("zero threshold disables denoising — publish everything")
	}
}

func TestGateIgnoresNonOdds(t *testing.T) {
	gate := oddschange.NewGate(0.5, oddschange.NewMemoryStore(), time.Hour)
	now := time.Now().UTC()
	ref := source.SourceRef{SourceID: "api_football", ObservedAt: now, Confidence: 0.9}
	c, err := event.NewCanonical(
		uuid.New(),
		event.Identity{Sport: sport.Football, CompetitionID: oddsCompID, MatchID: oddsMatchID, EventType: "match.result"},
		"", now, map[string]any{"score": "1-0"}, []source.SourceRef{ref}, 0.9,
	)
	if err != nil {
		t.Fatal(err)
	}
	if ok, _ := gate.ShouldPublish(context.Background(), c); !ok {
		t.Error("non-odds events must always pass the gate")
	}
}
