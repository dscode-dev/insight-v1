// Dead-letter HTTP handlers — Sprint 5.1.
//
//	GET  /v1/dlq                — paginated list of failures
//	GET  /v1/dlq/{id}            — single failure
//	POST /v1/dlq/{id}/replay     — re-enqueue a fresh SyncJob + stamp replayed_at
//
// Read-only by default. The replay endpoint MUTATES — it enqueues a
// NEW SyncJob with the same provider/competition/sync_type and
// CurrentAttempt=0. The original DLQ row stays intact so the audit
// trail survives.
//
// Architectural rule: only the composition root wires these
// handlers; the application layer never sees the ports.JobQueue or
// the ports.DeadLetterReader on the HTTP surface.
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// DLQConfig — wired by main.go.
type DLQConfig struct {
	Reader ports.DeadLetterReader
	// ReplayEnqueuer is a narrow shim onto ports.JobQueue.Enqueue.
	// Defined here so the handler doesn't pull in the full JobQueue
	// surface (Dequeue/Settle/etc.) that has no role on this route.
	Enqueuer ReplayEnqueuer
}

type ReplayEnqueuer interface {
	Enqueue(ctx context.Context, job syncdom.SyncJob) error
}

// DLQListResponse — wire shape returned by GET /v1/dlq.
type DLQListResponse struct {
	Items  []DLQItem `json:"items"`
	Limit  int       `json:"limit"`
	Offset int       `json:"offset"`
}

// DLQItem — wire shape for a single failure. Distinct from
// ports.DeadLetterRecord so we can evolve the JSON without churning
// the port.
type DLQItem struct {
	ID            string     `json:"id"`
	JobID         string     `json:"job_id"`
	ProviderID    string     `json:"provider_id"`
	CompetitionID string     `json:"competition_id"`
	SyncType      string     `json:"sync_type"`
	Reason        string     `json:"reason"`
	FailureType   string     `json:"failure_type"`
	Attempts      int        `json:"attempts"`
	FailedAt      time.Time  `json:"failed_at"`
	ReplayedAt    *time.Time `json:"replayed_at,omitempty"`
}

func toItem(rec ports.DeadLetterRecord) DLQItem {
	return DLQItem{
		ID:            rec.ID,
		JobID:         rec.Failure.JobID.String(),
		ProviderID:    rec.Failure.ProviderID,
		CompetitionID: rec.Failure.CompetitionID.String(),
		SyncType:      string(rec.Failure.SyncType),
		Reason:        rec.Failure.Reason,
		FailureType:   string(syncdom.ClassifyReason(rec.Failure.Reason)),
		Attempts:      rec.Failure.Attempts,
		FailedAt:      rec.Failure.FailedAt,
		ReplayedAt:    rec.ReplayedAt,
	}
}

// DLQListHandler — GET /v1/dlq.
//
// Query params: provider, failure_type, unreplayed (1/0), limit, offset.
func DLQListHandler(cfg DLQConfig) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := ports.DeadLetterQuery{
			Provider:    r.URL.Query().Get("provider"),
			FailureType: r.URL.Query().Get("failure_type"),
		}
		if v := r.URL.Query().Get("unreplayed"); v == "1" || v == "true" {
			q.Unreplayed = true
		}
		if v := r.URL.Query().Get("limit"); v != "" {
			if n, err := strconv.Atoi(v); err == nil {
				q.Limit = n
			}
		}
		if v := r.URL.Query().Get("offset"); v != "" {
			if n, err := strconv.Atoi(v); err == nil {
				q.Offset = n
			}
		}
		recs, err := cfg.Reader.List(r.Context(), q)
		if err != nil {
			http.Error(w, "dlq list failed", http.StatusInternalServerError)
			return
		}
		out := DLQListResponse{
			Items:  make([]DLQItem, 0, len(recs)),
			Limit:  q.Limit,
			Offset: q.Offset,
		}
		for _, r := range recs {
			out.Items = append(out.Items, toItem(r))
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(w).Encode(out)
	})
}

// DLQGetHandler — GET /v1/dlq/{id}.
//
// `{id}` is the last path segment. ServeMux's pattern matching is
// enough here; admin endpoints don't need a router.
func DLQGetHandler(cfg DLQConfig) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := lastPathSegment(r.URL.Path)
		if id == "" {
			http.Error(w, "missing id", http.StatusBadRequest)
			return
		}
		rec, err := cfg.Reader.Get(r.Context(), id)
		if errors.Is(err, ports.ErrNotFound) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if err != nil {
			http.Error(w, "dlq get failed", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(w).Encode(toItem(rec))
	})
}

// DLQReplayHandler — POST /v1/dlq/{id}/replay.
//
// Reads the row, builds a fresh SyncJob (new JobID, attempt=0),
// enqueues it, then stamps replayed_at on the original row. The
// original row is NOT marked Acked — by design: the audit trail
// shows "this failure existed AND was replayed at T".
func DLQReplayHandler(cfg DLQConfig) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		id := replayIDFromPath(r.URL.Path)
		if id == "" {
			http.Error(w, "missing id", http.StatusBadRequest)
			return
		}
		rec, err := cfg.Reader.Get(r.Context(), id)
		if errors.Is(err, ports.ErrNotFound) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if err != nil {
			http.Error(w, "dlq get failed", http.StatusInternalServerError)
			return
		}
		// A DLQ row represents one terminal failure and may be replayed once.
		// Repeated administrative delivery must not enqueue duplicate jobs.
		if rec.ReplayedAt != nil {
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status":      "already_replayed",
				"dlq_id":      id,
				"replayed_at": rec.ReplayedAt,
			})
			return
		}
		// Build a fresh SyncJob — same provider/competition/sync_type,
		// fresh JobID, scheduled_at = now. Replay is INTENTIONALLY a
		// brand-new chain; the original failure stays in the table.
		fresh, err := syncdom.NewSyncJob(
			syncdom.NewJobID(),
			rec.Failure.ProviderID,
			rec.Failure.CompetitionID,
			rec.Failure.SyncType,
			syncdom.PriorityNormal,
			time.Now(),
			map[string]string{
				"replayed_from":   rec.ID,
				"original_job_id": rec.Failure.JobID.String(),
			},
		)
		if err != nil {
			http.Error(w, "build replay job: "+err.Error(), http.StatusBadRequest)
			return
		}
		if err := cfg.Enqueuer.Enqueue(r.Context(), fresh); err != nil {
			http.Error(w, "enqueue replay: "+err.Error(), http.StatusInternalServerError)
			return
		}
		if err := cfg.Reader.MarkReplayed(r.Context(), id, time.Now()); err != nil {
			// Replay already enqueued — degraded but not fatal. Surface 200
			// with a warning header so the admin UI can show it.
			w.Header().Set("X-Insight-Warning", "mark_replayed_failed")
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status":       "replayed",
			"dlq_id":       id,
			"new_job_id":   fresh.JobID.String(),
			"original_job": rec.Failure.JobID.String(),
		})
	})
}

// lastPathSegment — for GET /v1/dlq/{id}.
func lastPathSegment(p string) string {
	idx := strings.LastIndex(p, "/")
	if idx < 0 || idx == len(p)-1 {
		return ""
	}
	return p[idx+1:]
}

// replayIDFromPath — for POST /v1/dlq/{id}/replay; strips the
// trailing "/replay" before extracting the id.
func replayIDFromPath(p string) string {
	p = strings.TrimSuffix(p, "/replay")
	id := lastPathSegment(p)
	// Validate UUID shape so we don't push arbitrary strings into
	// the Reader.Get call.
	if _, err := uuid.Parse(id); err != nil {
		return ""
	}
	return id
}
