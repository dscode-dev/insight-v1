// Sprint 3 — read-only audit APIs. Every communication-intelligence
// artefact (states, decisions, clusters, evolution) is inspectable.
package httpapi

import (
	"context"
	"net/http"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/application/narrativehealth"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// HealthComputer — the slice of the narrative health engine the audit
// surface exposes.
type HealthComputer interface {
	ComputeRecent(ctx context.Context, limit int) ([]narrativehealth.StoryHealth, error)
}

// AuditDeps — the read-only repositories the audit surface exposes.
type AuditDeps struct {
	States    ports.AgentStateRepository
	Decisions ports.DecisionRepository
	Clusters  ports.ClusterRepository
	Evolution ports.EvolutionRepository
	Health    HealthComputer
}

func limitParam(r *http.Request) int {
	if raw := r.URL.Query().Get("limit"); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 && n <= 500 {
			return n
		}
	}
	return 50
}

func mountAudit(mux *http.ServeMux, deps AuditDeps, logger zerolog.Logger) {
	mux.HandleFunc("GET /v1/agents/{id}/state", func(w http.ResponseWriter, r *http.Request) {
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid id"})
			return
		}
		states, err := deps.States.ListByAgent(r.Context(), id, limitParam(r))
		if err != nil {
			httpError(w, logger, err)
			return
		}
		out := make([]map[string]any, 0, len(states))
		for _, s := range states {
			out = append(out, map[string]any{
				"id":            s.ID.String(),
				"agent_id":      s.AgentID.String(),
				"match_id":      s.MatchID,
				"cluster_id":    s.ClusterID.String(),
				"cluster_type":  s.ClusterType,
				"current_state": string(s.Current),
				"history":       s.History,
				"created_at":    s.CreatedAt.Format(time.RFC3339),
				"updated_at":    s.UpdatedAt.Format(time.RFC3339),
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"states": out})
	})

	mux.HandleFunc("GET /v1/publication-decisions", func(w http.ResponseWriter, r *http.Request) {
		decisions, err := deps.Decisions.List(r.Context(), limitParam(r))
		if err != nil {
			httpError(w, logger, err)
			return
		}
		out := make([]map[string]any, 0, len(decisions))
		for _, d := range decisions {
			out = append(out, map[string]any{
				"id":         d.ID.String(),
				"agent_id":   d.AgentID.String(),
				"trend_id":   d.TrendID,
				"cluster_id": d.ClusterID.String(),
				"match_id":   d.MatchID,
				"action":     string(d.Action),
				"priority":   string(d.Priority),
				"reasoning":  d.Reasoning,
				"confidence": d.Confidence,
				"created_at": d.CreatedAt.Format(time.RFC3339),
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"decisions": out})
	})

	mux.HandleFunc("GET /v1/trend-clusters", func(w http.ResponseWriter, r *http.Request) {
		clusters, err := deps.Clusters.List(r.Context(), limitParam(r))
		if err != nil {
			httpError(w, logger, err)
			return
		}
		out := make([]map[string]any, 0, len(clusters))
		for _, c := range clusters {
			entry := map[string]any{
				"id":           c.ID.String(),
				"match_id":     c.MatchID,
				"cluster_type": string(c.ClusterType),
				"trend_ids":    c.TrendIDs,
				"trend_types":  c.TrendTypes,
				"confidence":   c.Confidence,
				"state":        string(c.State),
				"close_reason": c.CloseReason,
				"opened_at":    c.OpenedAt.Format(time.RFC3339),
				"created_at":   c.CreatedAt.Format(time.RFC3339),
				"updated_at":   c.UpdatedAt.Format(time.RFC3339),
			}
			if c.ClosedAt != nil {
				entry["closed_at"] = c.ClosedAt.Format(time.RFC3339)
			}
			out = append(out, entry)
		}
		writeJSON(w, http.StatusOK, map[string]any{"clusters": out})
	})

	mux.HandleFunc("GET /v1/narrative-health", func(w http.ResponseWriter, r *http.Request) {
		if deps.Health == nil {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "not configured"})
			return
		}
		health, err := deps.Health.ComputeRecent(r.Context(), limitParam(r))
		if err != nil {
			httpError(w, logger, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"stories": health})
	})

	mux.HandleFunc("GET /v1/drafts/evolution", func(w http.ResponseWriter, r *http.Request) {
		records, err := deps.Evolution.List(r.Context(), limitParam(r))
		if err != nil {
			httpError(w, logger, err)
			return
		}
		out := make([]map[string]any, 0, len(records))
		for _, rec := range records {
			out = append(out, map[string]any{
				"id":         rec.ID.String(),
				"agent_id":   rec.AgentID.String(),
				"cluster_id": rec.ClusterID.String(),
				"draft_id":   rec.DraftID.String(),
				"match_id":   rec.MatchID,
				"draft_type": string(rec.DraftType),
				"sequence":   rec.Sequence,
				"created_at": rec.CreatedAt.Format(time.RFC3339),
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"evolution": out})
	})
}
