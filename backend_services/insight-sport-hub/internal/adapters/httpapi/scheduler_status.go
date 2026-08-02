// Scheduler status HTTP handler — Sprint 3.
//
//	GET /v1/scheduler/status
//
// Returns the scheduler's tick loop snapshot + queue depth +
// active-worker count + the set of registered providers and enabled
// competitions. Read-only; the response is computed at request time.
//
// This is the admin-tooling surface for the future dashboard.
package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/application/scheduler"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// SchedulerSnapshotSource is the narrow surface this handler needs
// from the Scheduler. Defined locally so the http package doesn't
// pull in concrete scheduler internals.
type SchedulerSnapshotSource interface {
	Snapshot() scheduler.Snapshot
}

// QueueSizer — Len-only view of the queue.
type QueueSizer interface {
	Len() int
}

// SchedulerStatusConfig — every dependency the handler reads at
// request time. All fields required; main.go fills them.
type SchedulerStatusConfig struct {
	Scheduler SchedulerSnapshotSource
	Queue     QueueSizer
	// QueueStats — optional. When the active queue impl satisfies
	// ports.StatsReporter the handler reports redis_connected,
	// stream_depth, pending_messages, retry_queue_size,
	// active_consumers. In-memory queues set these to zero.
	QueueStats          ports.StatsReporter
	Workers             int
	RegisteredProviders []string
	Competitions        ports.CompetitionRegistry
	NextJobsLimit       int
}

// SchedulerStatusResponse — the wire shape consumed by admin UI.
type SchedulerStatusResponse struct {
	SchedulerRunning     bool          `json:"scheduler_running"`
	IntervalSeconds      int64         `json:"interval_seconds"`
	Ticks                int64         `json:"ticks_total"`
	JobsCreatedTotal     int64         `json:"jobs_created_total"`
	LastTickAt           time.Time     `json:"last_tick_at,omitempty"`
	QueueSize            int           `json:"queue_size"`
	ActiveWorkers        int           `json:"active_workers"`
	RegisteredProviders  []string      `json:"registered_providers"`
	EnabledCompetitions  []Competition `json:"enabled_competitions"`
	DisabledCompetitions []Competition `json:"disabled_competitions"`

	// Sprint 4 — queue-transport diagnostics. Always present; zero
	// values when the active queue impl is in-memory.
	RedisConnected  bool  `json:"redis_connected"`
	StreamDepth     int64 `json:"stream_depth"`
	ActiveConsumers int64 `json:"active_consumers"`
	PendingMessages int64 `json:"pending_messages"`
	RetryQueueSize  int64 `json:"retry_queue_size"`
}

// Competition — wire shape mirroring ports.Competition.
type Competition struct {
	ID          string `json:"id"`
	Slug        string `json:"slug"`
	Name        string `json:"name"`
	CountryCode string `json:"country_code"`
}

// SchedulerStatusHandler returns the GET /v1/scheduler/status handler.
func SchedulerStatusHandler(cfg SchedulerStatusConfig) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		enabled, disabled := loadCompetitions(r.Context(), cfg.Competitions)
		snap := cfg.Scheduler.Snapshot()
		var qs ports.QueueStats
		if cfg.QueueStats != nil {
			qs = cfg.QueueStats.Stats(r.Context())
		} else {
			qs.Connected = true
		}
		resp := SchedulerStatusResponse{
			SchedulerRunning:     snap.Running,
			IntervalSeconds:      int64(snap.Interval.Seconds()),
			Ticks:                snap.Ticks,
			JobsCreatedTotal:     snap.JobsCreatedTotal,
			LastTickAt:           snap.LastTickAt,
			QueueSize:            cfg.Queue.Len(),
			ActiveWorkers:        cfg.Workers,
			RegisteredProviders:  cfg.RegisteredProviders,
			EnabledCompetitions:  enabled,
			DisabledCompetitions: disabled,
			RedisConnected:       qs.Connected,
			StreamDepth:          qs.StreamDepth,
			ActiveConsumers:      qs.ActiveConsumers,
			PendingMessages:      qs.PendingMessages,
			RetryQueueSize:       qs.RetryQueueSize,
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(w).Encode(resp)
	})
}

// loadCompetitions returns enabled + disabled bucketed lists. Errors
// surface as empty slices — the endpoint is observational, never a
// hot path.
func loadCompetitions(
	ctx context.Context, registry ports.CompetitionRegistry,
) (enabled, disabled []Competition) {
	if registry == nil {
		return nil, nil
	}
	comps, err := registry.List(ctx)
	if err != nil {
		return nil, nil
	}
	for _, c := range comps {
		entry := Competition{
			ID:          c.ID.String(),
			Slug:        c.Slug,
			Name:        c.Name,
			CountryCode: c.CountryCode,
		}
		if c.Enabled {
			enabled = append(enabled, entry)
		} else {
			disabled = append(disabled, entry)
		}
	}
	return enabled, disabled
}
