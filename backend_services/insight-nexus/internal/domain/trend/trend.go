// Package trend — Nexus's READ-ONLY view of the Atlas Trend Contract.
//
// Nexus consumes insight:stream:trends and nothing else: never raw
// events, never Sport Hub streams, never Atlas databases. This type
// decodes the published wire envelope; Nexus never re-derives or
// reinterprets intelligence — Atlas's evaluation fields are consumed
// verbatim.
package trend

import (
	"encoding/json"
	"errors"
	"fmt"
)

// Supported Atlas trend schema versions. The contract is strictly
// additive: v4 (historical_context, market_memory, competition_context,
// regime, continuation) carries every v1–v3 field, so all versions
// decode through the same shape; v4-only sections ride in the untyped
// maps. Keep this set in lockstep with Atlas's TREND_SCHEMA_VERSION
// (atlas/trends/models.py) — the shared golden-fixture test in
// tests/contract fails when they drift.
var supportedSchemas = map[string]bool{"v1": true, "v2": true, "v3": true, "v4": true}

var (
	ErrMissingTrendID   = errors.New("trend: trend_id required")
	ErrMissingTrendType = errors.New("trend: trend_type required")
	ErrMissingMatchID   = errors.New("trend: match_id required")
	// ErrUnsupportedSchema marks a contract-violation decode failure
	// (vs malformed JSON). Both are poison; DLQ entries record which.
	ErrUnsupportedSchema = errors.New("trend: unsupported schema_version")
)

// Event is the decoded Atlas trend. Field names mirror the wire
// contract; everything is data — no behaviour beyond decoding.
type Event struct {
	TrendID           string         `json:"trend_id"`
	SchemaVersion     string         `json:"schema_version"`
	TrendType         string         `json:"trend_type"`
	Category          string         `json:"category"`
	Agent             string         `json:"agent"`
	Confidence        float64        `json:"confidence"`
	Severity          string         `json:"severity"`
	CompetitionID     string         `json:"competition_id"`
	MatchID           string         `json:"match_id"`
	Minute            *int           `json:"minute"`
	Strength          float64        `json:"strength"`
	Direction         int            `json:"direction"`
	CreatedAt         string         `json:"created_at"`
	Title             string         `json:"title"`
	Summary           string         `json:"summary"`
	Signals           []string       `json:"signals"`
	Metrics           map[string]any `json:"metrics"`
	ChartData         map[string]any `json:"chart_data"`
	PublishScore      *float64       `json:"publish_score"`
	PublicationTier   string         `json:"publication_tier"`
	LifecycleState    string         `json:"lifecycle_state"`
	CorrelationIDs    []string       `json:"correlation_ids"`
	Meaning           string         `json:"meaning"`
	MeaningCategory   string         `json:"meaning_category"`
	MeaningConfidence *float64       `json:"meaning_confidence"`
	Timeline          map[string]any `json:"timeline"`
	Pattern           map[string]any `json:"pattern"`
}

// Envelope is the stream payload shape Atlas XADDs: the trend plus the
// top-level priority flag.
type Envelope struct {
	SchemaVersion string `json:"schema_version"`
	Priority      bool   `json:"priority"`
	Trend         Event  `json:"trend"`
}

// DecodeEnvelope parses + validates one stream payload.
func DecodeEnvelope(payload []byte) (Envelope, error) {
	var env Envelope
	if err := json.Unmarshal(payload, &env); err != nil {
		return Envelope{}, fmt.Errorf("trend: decode envelope: %w", err)
	}
	if !supportedSchemas[env.SchemaVersion] {
		return Envelope{}, fmt.Errorf("%w %q", ErrUnsupportedSchema, env.SchemaVersion)
	}
	if err := env.Trend.validate(); err != nil {
		return Envelope{}, err
	}
	return env, nil
}

func (e Event) validate() error {
	if e.TrendID == "" {
		return ErrMissingTrendID
	}
	if e.TrendType == "" {
		return ErrMissingTrendType
	}
	if e.MatchID == "" {
		return ErrMissingMatchID
	}
	return nil
}

// PreviousStates extracts the lifecycle timeline's prior states
// (Contract V3 A2). Empty for v1/v2 producers.
func (e Event) PreviousStates() []string {
	raw, ok := e.Timeline["previous_states"]
	if !ok {
		return nil
	}
	items, ok := raw.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(items))
	for _, item := range items {
		if s, ok := item.(string); ok {
			out = append(out, s)
		}
	}
	return out
}
