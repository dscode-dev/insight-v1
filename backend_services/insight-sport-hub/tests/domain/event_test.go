package domain_test

import (
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

func newValidRaw(t *testing.T) *event.RawSportsEvent {
	t.Helper()
	raw, err := event.NewRaw(
		uuid.New(),
		validRef(t),
		sport.Football,
		uuid.New(),
		"external-match-1",
		"match.started",
		time.Now().UTC(),
		map[string]any{"score_home": 0, "score_away": 0},
		0.9,
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	return raw
}

// ----- RawSportsEvent -----

func TestRawRejectsEmptyPayload(t *testing.T) {
	_, err := event.NewRaw(
		uuid.New(), validRef(t), sport.Football, uuid.New(),
		"ext", "match.started", time.Now().UTC(),
		map[string]any{}, 0.9,
	)
	if err == nil {
		t.Error("expected error for empty payload")
	}
}

func TestRawRejectsUnsupportedSport(t *testing.T) {
	_, err := event.NewRaw(
		uuid.New(), validRef(t), sport.Sport("basketball"),
		uuid.New(), "ext", "match.started", time.Now().UTC(),
		map[string]any{"k": "v"}, 0.9,
	)
	if err == nil {
		t.Error("expected error for unsupported sport")
	}
}

func TestRawRejectsConfidenceOutOfRange(t *testing.T) {
	for _, bad := range []float64{-0.1, 1.5} {
		_, err := event.NewRaw(
			uuid.New(), validRef(t), sport.Football, uuid.New(),
			"ext", "match.started", time.Now().UTC(),
			map[string]any{"k": "v"}, bad,
		)
		if err == nil {
			t.Errorf("expected error for confidence %v", bad)
		}
	}
}

func TestRawPayloadIsDefensivelyCopied(t *testing.T) {
	payload := map[string]any{"k": "v"}
	raw, err := event.NewRaw(
		uuid.New(), validRef(t), sport.Football, uuid.New(),
		"ext", "match.started", time.Now().UTC(),
		payload, 0.9,
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	// Mutating the caller's map MUST NOT change the persisted raw.
	payload["k"] = "leaked"
	if got := raw.Payload()["k"]; got != "v" {
		t.Errorf("payload mutated through caller's reference: got %v", got)
	}
}

// ----- CanonicalSportsEvent -----

func TestCanonicalRequiresSources(t *testing.T) {
	_, err := event.NewCanonical(
		uuid.New(),
		event.Identity{
			Sport: sport.Football, CompetitionID: uuid.New(),
			MatchID: uuid.New(), EventType: "match.started",
		},
		"2026",
		time.Now().UTC(),
		map[string]any{"k": "v"},
		nil,
		0.5,
	)
	if err == nil {
		t.Error("expected error for empty sources")
	}
}

func TestCanonicalAddSourceIdempotent(t *testing.T) {
	c, err := event.NewCanonical(
		uuid.New(),
		event.Identity{
			Sport: sport.Football, CompetitionID: uuid.New(),
			MatchID: uuid.New(), EventType: "match.started",
		},
		"2026",
		time.Now().UTC(),
		map[string]any{"k": "v"},
		[]source.SourceRef{validRef(t)},
		0.5,
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	startCount := c.SourceCount()

	// Same ref again — should be a no-op (same source_id + observed_at).
	if err := c.AddSource(c.Sources()[0]); err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if c.SourceCount() != startCount {
		t.Errorf("AddSource not idempotent: count went from %d to %d",
			startCount, c.SourceCount())
	}
}

func TestCanonicalStatusTransition(t *testing.T) {
	c, _ := event.NewCanonical(
		uuid.New(),
		event.Identity{
			Sport: sport.Football, CompetitionID: uuid.New(),
			MatchID: uuid.New(), EventType: "match.started",
		},
		"2026",
		time.Now().UTC(),
		map[string]any{"k": "v"},
		[]source.SourceRef{validRef(t)},
		0.5,
	)
	if c.Status() != event.StatusCandidate {
		t.Errorf("initial status should be candidate, got %v", c.Status())
	}
	if err := c.UpdateStatus(event.StatusConfirmed); err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if c.Status() != event.StatusConfirmed {
		t.Error("UpdateStatus did not flip")
	}
	if err := c.UpdateStatus(event.Status("bogus")); err == nil {
		t.Error("expected error for invalid status")
	}
}

func TestCanonicalSourcesAreDefensivelyCopied(t *testing.T) {
	ref := validRef(t)
	c, _ := event.NewCanonical(
		uuid.New(),
		event.Identity{
			Sport: sport.Football, CompetitionID: uuid.New(),
			MatchID: uuid.New(), EventType: "match.started",
		},
		"2026",
		time.Now().UTC(),
		map[string]any{"k": "v"},
		[]source.SourceRef{ref},
		0.5,
	)
	got := c.Sources()
	got[0].SourceID = "leaked"
	// Mutating the returned slice MUST NOT affect canonical state.
	if c.Sources()[0].SourceID != ref.SourceID {
		t.Error("canonical's sources mutated through accessor")
	}
}

// ----- Identity -----

func TestIdentityEqual(t *testing.T) {
	a := event.Identity{
		Sport: sport.Football, CompetitionID: uuid.New(),
		MatchID: uuid.New(), EventType: "x",
	}
	b := a
	if !a.Equal(b) {
		t.Error("identical identities should compare equal")
	}
	b.EventType = "y"
	if a.Equal(b) {
		t.Error("differing event_type should compare unequal")
	}
}

func TestIdentityIsZero(t *testing.T) {
	z := event.Identity{}
	if !z.IsZero() {
		t.Error("zero-value identity should report IsZero")
	}
	complete := event.Identity{
		Sport: sport.Football, CompetitionID: uuid.New(),
		MatchID: uuid.New(), EventType: "x",
	}
	if complete.IsZero() {
		t.Error("complete identity should not report IsZero")
	}
}

// Sanity that newValidRaw fixture is reachable (compile-time guard).
func TestNewValidRawFixture(t *testing.T) {
	r := newValidRaw(t)
	if r == nil {
		t.Fatal("expected non-nil raw")
	}
}
