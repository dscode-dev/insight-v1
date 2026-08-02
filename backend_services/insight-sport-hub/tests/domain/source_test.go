// Domain-layer tests — invariants enforced by Source + SourceRef +
// SourceType + Sport constructors.
package domain_test

import (
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
)

// ----- SourceType -----

func TestSourceTypeMirrorAtlas(t *testing.T) {
	// Exact set + slugs of the Sprint 0.1 Atlas enum. Reordering /
	// renaming any value here is a wire-compatibility violation.
	want := map[source.SourceType]bool{
		source.TypeOfficialAPI:    true,
		source.TypeCommercialAPI:  true,
		source.TypeOfficialClub:   true,
		source.TypeOfficialLeague: true,
		source.TypeTrustedMedia:   true,
		source.TypeInternalBot:    true,
		source.TypeCommunity:      true,
		source.TypeUnknown:        true,
	}
	for _, got := range source.AllTypes() {
		if !want[got] {
			t.Errorf("unexpected SourceType slug %q", got)
		}
		delete(want, got)
	}
	if len(want) != 0 {
		t.Errorf("missing SourceType values: %v", want)
	}
}

func TestParseSourceType(t *testing.T) {
	if _, err := source.ParseSourceType("api_football"); err == nil {
		t.Error("expected error for unknown slug, got nil")
	}
	got, err := source.ParseSourceType("commercial_api")
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if got != source.TypeCommercialAPI {
		t.Errorf("got %v, want commercial_api", got)
	}
}

func TestIsCandidate(t *testing.T) {
	if !source.IsCandidate(source.TypeInternalBot) {
		t.Error("internal_bot must be candidate")
	}
	if !source.IsCandidate(source.TypeCommunity) {
		t.Error("community must be candidate")
	}
	if !source.IsCandidate(source.TypeUnknown) {
		t.Error("unknown must be candidate")
	}
	if source.IsCandidate(source.TypeOfficialAPI) {
		t.Error("official_api must NOT be candidate")
	}
	if source.IsCandidate(source.TypeCommercialAPI) {
		t.Error("commercial_api must NOT be candidate")
	}
}

// ----- SourceRef -----

func validRef(t *testing.T) source.SourceRef {
	t.Helper()
	return source.SourceRef{
		SourceID:   "api_football",
		SourceName: "API-Football v3",
		Type:       source.TypeCommercialAPI,
		Confidence: 0.95,
		ObservedAt: time.Now().UTC(),
	}
}

func TestSourceRefValidatePasses(t *testing.T) {
	if err := validRef(t).Validate(); err != nil {
		t.Errorf("unexpected err: %v", err)
	}
}

func TestSourceRefRequiresID(t *testing.T) {
	r := validRef(t)
	r.SourceID = ""
	if err := r.Validate(); err == nil {
		t.Error("expected error for missing source_id")
	}
}

func TestSourceRefConfidenceRange(t *testing.T) {
	r := validRef(t)
	r.Confidence = 1.5
	if err := r.Validate(); err == nil {
		t.Error("expected error for confidence > 1")
	}
	r.Confidence = -0.1
	if err := r.Validate(); err == nil {
		t.Error("expected error for negative confidence")
	}
}

func TestSourceRefNormalisedFillsName(t *testing.T) {
	r := validRef(t)
	r.SourceName = ""
	r.Metadata = nil
	out := r.Normalised()
	if out.SourceName != r.SourceID {
		t.Errorf("source_name not filled from source_id: got %q", out.SourceName)
	}
	if out.Metadata == nil {
		t.Error("metadata should be initialised to empty map")
	}
}

// ----- Source aggregate -----

func TestSourceNewEnforcesInvariants(t *testing.T) {
	id := uuid.New()
	_, err := source.New(id, "", source.TypeCommercialAPI, 50, true, 0.9)
	if err == nil {
		t.Error("expected error for empty name")
	}
	_, err = source.New(id, "Foo", source.SourceType("bogus"), 50, true, 0.9)
	if err == nil {
		t.Error("expected error for unknown type")
	}
	_, err = source.New(id, "Foo", source.TypeCommercialAPI, -1, true, 0.9)
	if err == nil {
		t.Error("expected error for negative priority")
	}
	_, err = source.New(id, "Foo", source.TypeCommercialAPI, 50, true, 1.5)
	if err == nil {
		t.Error("expected error for confidence_weight > 1")
	}

	src, err := source.New(id, "API-Football", source.TypeCommercialAPI, 50, true, 0.9)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if src.Name() != "API-Football" {
		t.Errorf("name mismatch: %q", src.Name())
	}
}

func TestSourceEnableDisable(t *testing.T) {
	src, _ := source.New(uuid.New(), "Foo", source.TypeCommercialAPI, 50, true, 0.9)
	src.Disable()
	if src.Enabled() {
		t.Error("Disable did not flip")
	}
	src.Enable()
	if !src.Enabled() {
		t.Error("Enable did not flip")
	}
}

func TestSourceChangeWeightAndPriority(t *testing.T) {
	src, _ := source.New(uuid.New(), "Foo", source.TypeCommercialAPI, 50, true, 0.9)
	if err := src.ChangeWeight(2.0); err == nil {
		t.Error("expected error for out-of-range weight")
	}
	if err := src.ChangeWeight(0.42); err != nil {
		t.Errorf("unexpected err: %v", err)
	}
	if src.ConfidenceWeight() != 0.42 {
		t.Errorf("weight not updated: %v", src.ConfidenceWeight())
	}
	if err := src.ChangePriority(-1); err == nil {
		t.Error("expected error for negative priority")
	}
}
