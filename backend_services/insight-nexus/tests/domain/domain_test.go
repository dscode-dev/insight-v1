// Domain contracts — agent, trend decode (Contract V3), draft, memory.
package domain_test

import (
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/trend"
)

func validAgent() agent.Agent {
	return agent.Agent{
		ID:         uuid.New(),
		Name:       "ninja",
		Specialty:  "Market Intelligence",
		Active:     true,
		TrendTypes: []string{"market_shift", "ninja"},
	}
}

func TestAgentValidation(t *testing.T) {
	if err := validAgent().Validate(); err != nil {
		t.Fatalf("valid agent rejected: %v", err)
	}
	a := validAgent()
	a.Name = " "
	if err := a.Validate(); err != agent.ErrMissingName {
		t.Errorf("blank name must fail: %v", err)
	}
	a = validAgent()
	a.TrendTypes = nil
	if err := a.Validate(); err != agent.ErrNoTrendTypes {
		t.Errorf("no trend types must fail: %v", err)
	}
}

func TestAgentConsumesTypeOrCategory(t *testing.T) {
	a := validAgent()
	if !a.Consumes("market_shift", "ninja") {
		t.Error("must consume by trend type")
	}
	if !a.Consumes("market_anomaly", "ninja") {
		t.Error("must consume by category")
	}
	if a.Consumes("pressure_building", "pulse") {
		t.Error("must not consume unrelated trends")
	}
}

func TestAgentQueueName(t *testing.T) {
	a := validAgent()
	if got := a.QueueName(); got != "insight:queue:nexus:ninja" {
		t.Errorf("queue name: %q", got)
	}
}

const v3Payload = `{
  "schema_version": "v3",
  "priority": true,
  "trend": {
    "trend_id": "0f0e0d0c-0b0a-4988-8877-665544332211",
    "schema_version": "v3",
    "trend_type": "market_conviction",
    "category": "fusion",
    "agent": "correlation",
    "confidence": 0.85,
    "severity": "high",
    "competition_id": "11111111-1111-4111-8111-111111111111",
    "match_id": "22222222-2222-4222-8222-222222222222",
    "minute": 71,
    "strength": 0.7,
    "direction": 1,
    "created_at": "2026-06-01T10:00:00+00:00",
    "title": "Market conviction building toward the home side",
    "summary": "Correlated market movement.",
    "signals": ["ODDS_SHIFT"],
    "metrics": {"prob_delta": 0.084},
    "chart_data": {"kind": "implied_probability", "series": []},
    "publish_score": 0.82,
    "publication_tier": "priority_publish",
    "lifecycle_state": "strengthening",
    "correlation_ids": ["33333333-3333-4333-8333-333333333333"],
    "meaning": "market_confidence_increasing",
    "meaning_category": "market_behavior",
    "meaning_confidence": 0.85,
    "timeline": {"previous_states": ["active", "strengthening"], "observation_count": 3},
    "pattern": {"pattern_id": "p1", "occurrences": 4, "historical_success_rate": 0.72}
  }
}`

func TestDecodeContractV3(t *testing.T) {
	env, err := trend.DecodeEnvelope([]byte(v3Payload))
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if !env.Priority {
		t.Error("priority flag lost")
	}
	ev := env.Trend
	if ev.TrendType != "market_conviction" || ev.Category != "fusion" {
		t.Errorf("identity lost: %+v", ev)
	}
	if ev.Meaning != "market_confidence_increasing" {
		t.Errorf("meaning lost: %q", ev.Meaning)
	}
	if ev.PublicationTier != "priority_publish" || *ev.PublishScore != 0.82 {
		t.Error("evaluation fields lost")
	}
	if got := ev.PreviousStates(); len(got) != 2 || got[0] != "active" {
		t.Errorf("timeline previous states: %v", got)
	}
	if ev.Pattern["occurrences"].(float64) != 4 {
		t.Error("pattern lost")
	}
}

func TestDecodeRejectsBadPayloads(t *testing.T) {
	if _, err := trend.DecodeEnvelope([]byte(`{"schema_version":"v99","trend":{}}`)); err == nil {
		t.Error("unsupported schema must fail")
	}
	if _, err := trend.DecodeEnvelope([]byte(`{"schema_version":"v3","trend":{"trend_type":"x","match_id":"y"}}`)); err == nil {
		t.Error("missing trend_id must fail")
	}
	if _, err := trend.DecodeEnvelope([]byte(`not json`)); err == nil {
		t.Error("malformed json must fail")
	}
}

func TestDraftAndMemoryValidation(t *testing.T) {
	d := draft.Draft{
		ID: uuid.New(), AgentID: uuid.New(), TrendID: "t1",
		Title: "x", Status: draft.StatusGenerated, CreatedAt: time.Now(),
	}
	if err := d.Validate(); err != nil {
		t.Errorf("valid draft rejected: %v", err)
	}
	d.Title = ""
	if err := d.Validate(); err != draft.ErrMissingTitle {
		t.Error("missing title must fail")
	}
	m := memory.Memory{ID: uuid.New(), AgentID: uuid.New(), Summary: "saw a thing"}
	if err := m.Validate(); err != nil {
		t.Errorf("valid memory rejected: %v", err)
	}
}
