// Provider status HTTP handler — Sprint 2.
//
//	GET /v1/providers/status
//
// Returns the in-memory snapshot for every registered adapter, in
// the shape future admin dashboards will consume. Read-only —
// snapshot is computed at request time from the
// ProviderStatusRecorder.
package httpapi

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// ProviderStatusResponse is the wire shape. Stable across Sprint 2;
// additive-only evolution as new health signals land.
type ProviderStatusResponse struct {
	Providers []ProviderEntry `json:"providers"`
}

type ProviderEntry struct {
	SourceID            string    `json:"source_id"`
	Reachable           bool      `json:"reachable"`
	LastSuccessfulSync  time.Time `json:"last_successful_sync,omitempty"`
	LastFailure         time.Time `json:"last_failure,omitempty"`
	LastError           string    `json:"last_error,omitempty"`
	AverageLatencyMs    int64     `json:"average_latency_ms"`
	RequestsTotal       int64     `json:"requests_total"`
	RequestsFailedTotal int64     `json:"requests_failed_total"`

	// Sprint 2.1 — static profile fields. Always present in the
	// response (zero values when unregistered) so admin tooling can
	// rely on a stable shape.
	Capabilities CapabilitiesEntry `json:"capabilities"`
	RatePolicy   RatePolicyEntry   `json:"rate_policy"`
	PollPolicies []PollPolicyEntry `json:"poll_policies"`

	// Sprint 3 — scheduler/runner lifecycle counters.
	QueuedJobs             int64     `json:"queued_jobs"`
	RunningJobs            int64     `json:"running_jobs"`
	CompletedJobs          int64     `json:"completed_jobs"`
	FailedJobs             int64     `json:"failed_jobs"`
	QueueDroppedTotal      int64     `json:"queue_dropped_total"`
	RateLimitBlockedTotal  int64     `json:"rate_limit_blocked_total"`
	LastExecution          time.Time `json:"last_execution,omitempty"`
	NextScheduledExecution time.Time `json:"next_scheduled_execution,omitempty"`
}

// CapabilitiesEntry — wire mirror of source.ProviderCapability.
type CapabilitiesEntry struct {
	SupportsFixtures           bool `json:"supports_fixtures"`
	SupportsHistoricalFixtures bool `json:"supports_historical_fixtures"`

	SupportsResults           bool `json:"supports_results"`
	SupportsHistoricalResults bool `json:"supports_historical_results"`

	SupportsStandings           bool `json:"supports_standings"`
	SupportsHistoricalStandings bool `json:"supports_historical_standings"`

	SupportsOdds           bool `json:"supports_odds"`
	SupportsHistoricalOdds bool `json:"supports_historical_odds"`

	SupportsPlayers           bool `json:"supports_players"`
	SupportsHistoricalPlayers bool `json:"supports_historical_players"`

	SupportsLineups           bool `json:"supports_lineups"`
	SupportsHistoricalLineups bool `json:"supports_historical_lineups"`

	SupportsInjuries           bool `json:"supports_injuries"`
	SupportsHistoricalInjuries bool `json:"supports_historical_injuries"`

	SupportsNews bool `json:"supports_news"`
}

// RatePolicyEntry — wire mirror of sync.RateLimitPolicy. Zero
// values are valid (unconfigured).
type RatePolicyEntry struct {
	RequestsPerMinute int `json:"requests_per_minute"`
	RequestsPerHour   int `json:"requests_per_hour"`
	DailyLimit        int `json:"daily_limit"`
	BurstLimit        int `json:"burst_limit"`
}

// PollPolicyEntry — wire mirror of sync.PollPolicy. Durations
// rendered in seconds for admin-UI ergonomics.
type PollPolicyEntry struct {
	SyncType        string `json:"sync_type"`
	IntervalSeconds int64  `json:"interval_seconds"`
	LiveSeconds     int64  `json:"live_interval_seconds,omitempty"`
	Enabled         bool   `json:"enabled"`
}

// ProvidersStatusHandler returns an http.Handler that serves the
// snapshot. The handler captures the recorder + the set of
// registered SourceIDs at construction so the response always
// includes every adapter (even ones that haven't been called yet).
func ProvidersStatusHandler(
	rec observability.ProviderStatusRecorder,
	registeredSourceIDs []string,
) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		all := rec.All()
		// Stable order — include every registered source, even with
		// zero-value snapshot (admin sees "not yet called").
		out := ProviderStatusResponse{
			Providers: make([]ProviderEntry, 0, len(registeredSourceIDs)),
		}
		for _, id := range registeredSourceIDs {
			s := all[id]
			if s.SourceID == "" {
				s.SourceID = id
			}
			out.Providers = append(out.Providers, toEntry(s))
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(w).Encode(out)
	})
}

func toEntry(s ports.HealthSnapshot) ProviderEntry {
	return ProviderEntry{
		SourceID:               s.SourceID,
		Reachable:              s.Reachable,
		LastSuccessfulSync:     s.LastSuccessfulSync,
		LastFailure:            s.LastFailure,
		LastError:              s.LastError,
		AverageLatencyMs:       s.AverageLatencyMs,
		RequestsTotal:          s.RequestsTotal,
		RequestsFailedTotal:    s.RequestsFailedTotal,
		Capabilities:           toCapabilitiesEntry(s.Capabilities),
		RatePolicy:             toRatePolicyEntry(s.RatePolicy),
		PollPolicies:           toPollPoliciesEntry(s.PollPolicies),
		QueuedJobs:             s.QueuedJobs,
		RunningJobs:            s.RunningJobs,
		CompletedJobs:          s.CompletedJobs,
		FailedJobs:             s.FailedJobs,
		QueueDroppedTotal:      s.QueueDroppedTotal,
		RateLimitBlockedTotal:  s.RateLimitBlockedTotal,
		LastExecution:          s.LastExecution,
		NextScheduledExecution: s.NextScheduledExecution,
	}
}

func toCapabilitiesEntry(c source.ProviderCapability) CapabilitiesEntry {
	return CapabilitiesEntry{
		SupportsFixtures:            c.SupportsFixtures,
		SupportsHistoricalFixtures:  c.SupportsHistoricalFixtures,
		SupportsResults:             c.SupportsResults,
		SupportsHistoricalResults:   c.SupportsHistoricalResults,
		SupportsStandings:           c.SupportsStandings,
		SupportsHistoricalStandings: c.SupportsHistoricalStandings,
		SupportsOdds:                c.SupportsOdds,
		SupportsHistoricalOdds:      c.SupportsHistoricalOdds,
		SupportsPlayers:             c.SupportsPlayers,
		SupportsHistoricalPlayers:   c.SupportsHistoricalPlayers,
		SupportsLineups:             c.SupportsLineups,
		SupportsHistoricalLineups:   c.SupportsHistoricalLineups,
		SupportsInjuries:            c.SupportsInjuries,
		SupportsHistoricalInjuries:  c.SupportsHistoricalInjuries,
		SupportsNews:                c.SupportsNews,
	}
}

func toRatePolicyEntry(p syncdom.RateLimitPolicy) RatePolicyEntry {
	return RatePolicyEntry{
		RequestsPerMinute: p.RequestsPerMinute,
		RequestsPerHour:   p.RequestsPerHour,
		DailyLimit:        p.DailyLimit,
		BurstLimit:        p.BurstLimit,
	}
}

func toPollPoliciesEntry(ps []syncdom.PollPolicy) []PollPolicyEntry {
	out := make([]PollPolicyEntry, 0, len(ps))
	for _, p := range ps {
		out = append(out, PollPolicyEntry{
			SyncType:        string(p.SyncType),
			IntervalSeconds: int64(p.Interval.Seconds()),
			LiveSeconds:     int64(p.LiveInterval.Seconds()),
			Enabled:         p.Enabled,
		})
	}
	return out
}
