// Cross-repo trend-contract guard — V1.1 closure (Sprint X finding H1).
//
// fixtures/trend_envelope_v4.json is GENERATED FROM ATLAS'S OWN
// SERIALIZER (Trend.to_wire + publisher envelope shape); the canonical
// copy lives in insight-protos/contracts/trends/. Atlas has the mirror
// test asserting its emitted wire form still equals the fixture.
//
// If Atlas bumps TREND_SCHEMA_VERSION or changes the wire shape, its
// mirror test forces the fixture to be regenerated — and this test
// then fails until Nexus actually decodes the new version. The two
// suites together make silent producer/consumer drift impossible.
package contract_test

import (
	"os"
	"testing"

	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
)

func loadFixture(t *testing.T) []byte {
	t.Helper()
	b, err := os.ReadFile("fixtures/trend_envelope_v4.json")
	if err != nil {
		t.Fatalf("fixture missing: %v", err)
	}
	return b
}

func TestAtlasV4EnvelopeDecodes(t *testing.T) {
	env, err := trend.DecodeEnvelope(loadFixture(t))
	if err != nil {
		t.Fatalf("Atlas's emitted envelope must decode in Nexus: %v", err)
	}
	if env.SchemaVersion != "v4" {
		t.Fatalf("schema_version = %q (fixture stale?)", env.SchemaVersion)
	}
	if !env.Priority {
		t.Fatal("priority flag lost")
	}
	e := env.Trend
	if e.TrendID != "f1e40000-0000-4000-8000-000000000001" {
		t.Fatalf("trend_id = %q", e.TrendID)
	}
	if e.MatchID != "f1e40000-0000-4000-8000-000000000002" {
		t.Fatalf("match_id = %q (canonical id must ride the v1 key)", e.MatchID)
	}
	if e.TrendType == "" || e.Category == "" || e.Agent == "" {
		t.Fatalf("routing fields lost: type=%q cat=%q agent=%q",
			e.TrendType, e.Category, e.Agent)
	}
	if e.Title == "" || e.Summary == "" {
		t.Fatal("deterministic draft fields (title/summary) lost")
	}
	if e.PublishScore == nil || *e.PublishScore != 0.78 {
		t.Fatalf("publish_score lost: %v", e.PublishScore)
	}
	if e.PublicationTier != "priority_publish" || e.LifecycleState != "confirmed" {
		t.Fatalf("evaluation fields lost: tier=%q state=%q",
			e.PublicationTier, e.LifecycleState)
	}
	if len(e.PreviousStates()) != 2 {
		t.Fatalf("timeline previous_states lost: %v", e.PreviousStates())
	}
}

func TestUnknownSchemaStillRejected(t *testing.T) {
	// v4 acceptance must not have degenerated into accept-anything.
	_, err := trend.DecodeEnvelope([]byte(
		`{"schema_version":"v99","priority":false,"trend":{"trend_id":"x","trend_type":"t","match_id":"m"}}`))
	if err == nil {
		t.Fatal("unknown schema accepted")
	}
}
