// Application-layer tests — exercises every service in isolation
// using small in-memory fakes. The boundary test in this package
// also enforces hexagonal architecture (no domain → adapter imports).
package application_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	appcanon "github.com/konoha-labs/insight-sports-hub/internal/application/canonicalization"
	appconfidence "github.com/konoha-labs/insight-sports-hub/internal/application/confidence"
	appconflict "github.com/konoha-labs/insight-sports-hub/internal/application/conflict"
	appnorm "github.com/konoha-labs/insight-sports-hub/internal/application/normalization"
	appval "github.com/konoha-labs/insight-sports-hub/internal/application/validation"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// ---------------------------------------------------------------------------
// Fakes — minimal in-memory implementations of the ports the tests touch.
// ---------------------------------------------------------------------------

type fakeClock struct{ now time.Time }

func (f *fakeClock) Now() time.Time { return f.now }

type fakeRawRepo struct {
	byID map[uuid.UUID]*event.RawSportsEvent
}

func newFakeRawRepo() *fakeRawRepo {
	return &fakeRawRepo{byID: map[uuid.UUID]*event.RawSportsEvent{}}
}

func (r *fakeRawRepo) Insert(_ context.Context, raw *event.RawSportsEvent) error {
	if _, ok := r.byID[raw.RawEventID()]; ok {
		return ports.ErrDuplicate
	}
	r.byID[raw.RawEventID()] = raw
	return nil
}
func (r *fakeRawRepo) GetByID(_ context.Context, id uuid.UUID) (*event.RawSportsEvent, error) {
	v, ok := r.byID[id]
	if !ok {
		return nil, ports.ErrNotFound
	}
	return v, nil
}
func (r *fakeRawRepo) ListForIdentity(_ context.Context, id event.Identity) ([]*event.RawSportsEvent, error) {
	out := []*event.RawSportsEvent{}
	for _, raw := range r.byID {
		// Light filter — sport + competition + event_type. Mirrors what
		// the real postgres adapter does pre-derived-match-filter.
		if raw.Sport() == id.Sport &&
			raw.CompetitionID() == id.CompetitionID &&
			raw.EventType() == id.EventType {
			out = append(out, raw)
		}
	}
	return out, nil
}
func (r *fakeRawRepo) ExistsByID(_ context.Context, id uuid.UUID) (bool, error) {
	_, ok := r.byID[id]
	return ok, nil
}

type permissiveCompRegistry struct{}

func (permissiveCompRegistry) IsKnown(
	_ context.Context,
	_ uuid.UUID,
) (bool, error) {
	return true, nil
}

func (permissiveCompRegistry) Register(
	_ context.Context,
	_ ports.Competition,
) error {
	return nil
}

func (permissiveCompRegistry) Lookup(
	_ context.Context,
	_ uuid.UUID,
) (ports.Competition, error) {
	return ports.Competition{}, nil
}

func (permissiveCompRegistry) LookupByExternalID(
	_ context.Context,
	_, _ string,
) (ports.Competition, error) {
	return ports.Competition{}, nil
}

func (permissiveCompRegistry) LinkExternalID(
	_ context.Context,
	_ uuid.UUID,
	_, _ string,
) error {
	return nil
}

func (permissiveCompRegistry) GetExternalIDForSource(
	_ context.Context,
	_ uuid.UUID,
	_ string,
) (string, error) {
	return "test-external-id", nil
}

func (permissiveCompRegistry) SetEnabled(
	_ context.Context,
	_ uuid.UUID,
	_ bool,
) error {
	return nil
}

func (permissiveCompRegistry) List(
	_ context.Context,
) ([]ports.Competition, error) {
	return []ports.Competition{}, nil
}

type noopMetrics struct{}

func (noopMetrics) IncRawIngested()          {}
func (noopMetrics) IncRawDuplicate()         {}
func (noopMetrics) IncCanonicalUpserted()    {}
func (noopMetrics) IncRejected(string)       {}
func (noopMetrics) IncConflict(string)       {}
func (noopMetrics) SetRegisteredSources(int) {}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func makeRef(id string, t source.SourceType, confidence float64) source.SourceRef {
	return source.SourceRef{
		SourceID:   id,
		SourceName: id,
		Type:       t,
		Confidence: confidence,
		ObservedAt: time.Now().UTC(),
	}
}

func makeRawInput(t *testing.T, ref source.SourceRef, payload map[string]any) appnorm.NormalizedInput {
	t.Helper()
	return appnorm.NormalizedInput{
		Source:          ref,
		SportRaw:        "football",
		CompetitionID:   uuid.New(),
		ExternalMatchID: "ext-1",
		EventType:       "match.started",
		ObservedAt:      time.Now().UTC(),
		Payload:         payload,
		RawConfidence:   0.85,
	}
}

// ---------------------------------------------------------------------------
// Normalization
// ---------------------------------------------------------------------------

func TestNormalizerProducesRaw(t *testing.T) {
	svc := appnorm.New()
	in := makeRawInput(t,
		makeRef("api_football", source.TypeCommercialAPI, 0.95),
		map[string]any{"score_home": 1, "score_away": 0},
	)
	raw, err := svc.Normalize(in)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if raw.Sport() != sport.Football {
		t.Errorf("expected football, got %v", raw.Sport())
	}
	// SourceRef preserved verbatim — lineage rule.
	if raw.Source().SourceID != "api_football" {
		t.Error("source ref not preserved")
	}
}

func TestNormalizerRejectsUnsupportedSport(t *testing.T) {
	svc := appnorm.New()
	in := makeRawInput(t,
		makeRef("api_football", source.TypeCommercialAPI, 0.95),
		map[string]any{"k": "v"},
	)
	in.SportRaw = "basketball"
	if _, err := svc.Normalize(in); err == nil {
		t.Error("expected error for unsupported sport")
	}
}

func TestNormalizerGeneratesIDWhenMissing(t *testing.T) {
	svc := appnorm.New()
	in := makeRawInput(t,
		makeRef("x", source.TypeCommercialAPI, 0.9),
		map[string]any{"k": "v"},
	)
	raw, err := svc.Normalize(in)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if raw.RawEventID() == uuid.Nil {
		t.Error("expected generated UUID")
	}
}

// Sprint 2.1 — adapter-built raws are still routed through
// NormalizerService.NormalizeRaw. The architectural seam exists so
// future cross-producer normalisation (timestamp harmonisation across
// non-HTTP sources, internal-bot pre-shaping, …) lands in one place.
//
// Current behaviour: pure pass-through. The returned raw IS the input
// raw — same pointer, same SourceRef, same payload identity.
func TestNormalizeRawIsPassThrough(t *testing.T) {
	svc := appnorm.New()
	in := makeRawInput(t,
		makeRef("api_football", source.TypeCommercialAPI, 0.95),
		map[string]any{"score_home": 1, "score_away": 0},
	)
	raw, err := svc.Normalize(in)
	if err != nil {
		t.Fatalf("unexpected normalize err: %v", err)
	}
	out, err := svc.NormalizeRaw(raw)
	if err != nil {
		t.Fatalf("unexpected pass-through err: %v", err)
	}
	if out != raw {
		t.Error("NormalizeRaw must return the SAME raw instance — pass-through, not a copy")
	}
	// SourceRef preservation — the architectural lineage rule.
	if out.Source().SourceID != raw.Source().SourceID {
		t.Error("SourceRef.SourceID lost across pass-through")
	}
	if out.RawEventID() != raw.RawEventID() {
		t.Error("RawEventID lost across pass-through")
	}
}

func TestNormalizeRawRejectsNil(t *testing.T) {
	svc := appnorm.New()
	if _, err := svc.NormalizeRaw(nil); err == nil {
		t.Error("expected error for nil raw")
	}
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

func TestValidationDuplicateRawID(t *testing.T) {
	rawRepo := newFakeRawRepo()
	clk := &fakeClock{now: time.Now().UTC()}
	svc := appval.New(rawRepo, permissiveCompRegistry{}, clk,
		noopMetrics{}, appval.Config{FutureSkew: 5 * time.Minute})

	raw, _ := event.NewRaw(
		uuid.New(), makeRef("x", source.TypeCommercialAPI, 0.9),
		sport.Football, uuid.New(), "ext-1", "match.started",
		clk.Now(), map[string]any{"k": "v"}, 0.85,
	)
	_ = rawRepo.Insert(context.Background(), raw)

	d := svc.Validate(context.Background(), raw)
	if !d.Quarantined || d.Reason != appval.ReasonDuplicateRawEventID {
		t.Errorf("expected duplicate quarantine, got %+v", d)
	}
}

func TestValidationFutureSkew(t *testing.T) {
	rawRepo := newFakeRawRepo()
	clk := &fakeClock{now: time.Now().UTC()}
	svc := appval.New(rawRepo, permissiveCompRegistry{}, clk,
		noopMetrics{}, appval.Config{FutureSkew: 5 * time.Minute})

	raw, _ := event.NewRaw(
		uuid.New(), makeRef("x", source.TypeCommercialAPI, 0.9),
		sport.Football, uuid.New(), "ext-1", "match.started",
		clk.Now().Add(30*time.Minute), map[string]any{"k": "v"}, 0.85,
	)
	d := svc.Validate(context.Background(), raw)
	if !d.Quarantined || d.Reason != appval.ReasonFutureEventBeyondBudget {
		t.Errorf("expected future-skew quarantine, got %+v", d)
	}
}

// ---------------------------------------------------------------------------
// Conflict detection
// ---------------------------------------------------------------------------

func TestConflictDetectionFlagsDisagreement(t *testing.T) {
	strategy := appconflict.NewFieldEqualityStrategy()
	svc := appconflict.New(strategy, nil)

	competition := uuid.New()
	r1, _ := event.NewRaw(
		uuid.New(), makeRef("api_football", source.TypeCommercialAPI, 0.95),
		sport.Football, competition, "ext-1", "match.started",
		time.Now().UTC(), map[string]any{"score_home": 1}, 0.9,
	)
	r2, _ := event.NewRaw(
		uuid.New(), makeRef("sportmonks", source.TypeCommercialAPI, 0.88),
		sport.Football, competition, "ext-1", "match.started",
		time.Now().UTC(), map[string]any{"score_home": 2}, 0.85,
	)

	res := svc.Detect([]*event.RawSportsEvent{r1, r2}, nil)
	if !res.Conflicts {
		t.Error("expected conflict between disagreeing authoritative raws")
	}
}

func TestConflictDetectionIgnoresCandidates(t *testing.T) {
	strategy := appconflict.NewFieldEqualityStrategy()
	svc := appconflict.New(strategy, nil)

	competition := uuid.New()
	auth, _ := event.NewRaw(
		uuid.New(), makeRef("api_football", source.TypeCommercialAPI, 0.95),
		sport.Football, competition, "ext-1", "match.started",
		time.Now().UTC(), map[string]any{"score_home": 1}, 0.9,
	)
	candidate, _ := event.NewRaw(
		uuid.New(), makeRef("crowd_bot", source.TypeInternalBot, 0.5),
		sport.Football, competition, "ext-1", "match.started",
		time.Now().UTC(), map[string]any{"score_home": 999}, 0.5,
	)

	res := svc.Detect([]*event.RawSportsEvent{auth, candidate}, nil)
	if res.Conflicts {
		t.Error("candidate disagreement should NOT count as conflict")
	}
}

// ---------------------------------------------------------------------------
// Confidence
// ---------------------------------------------------------------------------

func TestWeightedAverageWithKnownSource(t *testing.T) {
	svc := appconfidence.New(appconfidence.NewWeightedAveragePolicy())

	srcRef := makeRef("api_football", source.TypeCommercialAPI, 0.95)
	raw, _ := event.NewRaw(
		uuid.New(), srcRef, sport.Football, uuid.New(),
		"ext-1", "match.started", time.Now().UTC(),
		map[string]any{"k": "v"}, 0.8,
	)

	registered, _ := source.New(
		uuid.New(), "api_football", source.TypeCommercialAPI, 50, true, 0.7,
	)
	got := svc.Compute(
		[]*event.RawSportsEvent{raw},
		map[string]*source.Source{"api_football": registered},
	)
	// weight=0.7 (registered, overrides ref.Confidence=0.95)
	// raw_confidence=0.8
	// final = (0.7 * 0.8) / 0.7 = 0.8
	if got < 0.79 || got > 0.81 {
		t.Errorf("expected ~0.8, got %v", got)
	}
}

func TestWeightedAverageFallsBackToRefConfidence(t *testing.T) {
	svc := appconfidence.New(appconfidence.NewWeightedAveragePolicy())
	srcRef := makeRef("unknown_source", source.TypeCommunity, 0.6)
	raw, _ := event.NewRaw(
		uuid.New(), srcRef, sport.Football, uuid.New(),
		"ext-1", "match.started", time.Now().UTC(),
		map[string]any{"k": "v"}, 0.5,
	)
	got := svc.Compute([]*event.RawSportsEvent{raw}, nil)
	// fallback weight = ref.Confidence (0.6); raw = 0.5
	// final = (0.6 * 0.5) / 0.6 = 0.5
	if got < 0.49 || got > 0.51 {
		t.Errorf("expected ~0.5, got %v", got)
	}
}

// ---------------------------------------------------------------------------
// Canonicalization
// ---------------------------------------------------------------------------

func TestCanonicalizationBuildPreservesAllSources(t *testing.T) {
	svc := appcanon.New()

	competition := uuid.New()
	r1, _ := event.NewRaw(
		uuid.New(), makeRef("api_football", source.TypeCommercialAPI, 0.95),
		sport.Football, competition, "ext-1", "match.started",
		time.Now().UTC().Add(-2*time.Minute), map[string]any{"k": "older"}, 0.9,
	)
	r2, _ := event.NewRaw(
		uuid.New(), makeRef("sportmonks", source.TypeCommercialAPI, 0.88),
		sport.Football, competition, "ext-1", "match.started",
		time.Now().UTC(), map[string]any{"k": "newer"}, 0.85,
	)
	// SAME external_match_id + same source_id resolution → identical
	// derived match_id. For the test we use the SAME source_id so
	// both raws share an Identity.
	r2same, _ := event.NewRaw(
		uuid.New(), makeRef("api_football", source.TypeCommercialAPI, 0.88),
		sport.Football, competition, "ext-1", "match.started",
		time.Now().UTC(), map[string]any{"k": "newer"}, 0.85,
	)
	_ = r2

	c, err := svc.Build(uuid.New(),
		[]*event.RawSportsEvent{r1, r2same}, 0.75,
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if c.SourceCount() != 2 {
		t.Errorf("expected 2 sources preserved, got %d", c.SourceCount())
	}
	// Latest authoritative observation wins for the payload field.
	if got := c.Payload()["k"]; got != "newer" {
		t.Errorf("expected merged payload to take newer value, got %v", got)
	}
}

func TestCanonicalizationRejectsMixedIdentities(t *testing.T) {
	svc := appcanon.New()

	r1, _ := event.NewRaw(
		uuid.New(), makeRef("api_football", source.TypeCommercialAPI, 0.95),
		sport.Football, uuid.New(), "ext-A", "match.started",
		time.Now().UTC(), map[string]any{"k": "v"}, 0.9,
	)
	r2, _ := event.NewRaw(
		uuid.New(), makeRef("api_football", source.TypeCommercialAPI, 0.95),
		sport.Football, uuid.New(), "ext-B", "match.started",
		time.Now().UTC(), map[string]any{"k": "v"}, 0.9,
	)

	_, err := svc.Build(uuid.New(),
		[]*event.RawSportsEvent{r1, r2}, 0.5,
	)
	if err == nil {
		t.Error("expected error for mixed identities")
	}
}

// ---------------------------------------------------------------------------
// Lineage preservation — architectural rule check
// ---------------------------------------------------------------------------

func TestSourceRefSurvivesAllPipelineHops(t *testing.T) {
	// Build a raw → put it through canonicalization → assert the
	// canonical.sources[0] still matches the original ref byte-for-byte
	// on every architectural field. This is the "lineage preservation"
	// architectural rule from the Sprint 1 spec.
	originalRef := source.SourceRef{
		SourceID:       "api_football",
		SourceName:     "API-Football v3",
		Type:           source.TypeCommercialAPI,
		Confidence:     0.95,
		ObservedAt:     time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC),
		AdapterVersion: ptr("api_football@1.4.2"),
		Metadata: map[string]any{
			"endpoint": "/v3/fixtures/12345",
			"etag":     "W/\"abc-123\"",
		},
	}
	raw, err := event.NewRaw(
		uuid.New(), originalRef, sport.Football, uuid.New(),
		"ext-1", "match.started", time.Now().UTC(),
		map[string]any{"k": "v"}, 0.9,
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}

	c, err := appcanon.New().Build(uuid.New(),
		[]*event.RawSportsEvent{raw}, 0.85,
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}

	got := c.Sources()[0]
	if got.SourceID != originalRef.SourceID {
		t.Errorf("source_id lost: got %q", got.SourceID)
	}
	if got.SourceName != originalRef.SourceName {
		t.Errorf("source_name lost: got %q", got.SourceName)
	}
	if got.Type != originalRef.Type {
		t.Errorf("source_type lost: got %v", got.Type)
	}
	if got.Confidence != originalRef.Confidence {
		t.Errorf("confidence lost: got %v", got.Confidence)
	}
	if !got.ObservedAt.Equal(originalRef.ObservedAt) {
		t.Errorf("observed_at lost: got %v", got.ObservedAt)
	}
	if got.AdapterVersion == nil || *got.AdapterVersion != *originalRef.AdapterVersion {
		t.Errorf("adapter_version lost: got %v", got.AdapterVersion)
	}
	if got.Metadata["endpoint"] != originalRef.Metadata["endpoint"] {
		t.Errorf("metadata.endpoint lost: got %v", got.Metadata["endpoint"])
	}
	if got.Metadata["etag"] != originalRef.Metadata["etag"] {
		t.Errorf("metadata.etag lost: got %v", got.Metadata["etag"])
	}
}

func ptr[T any](v T) *T { return &v }
