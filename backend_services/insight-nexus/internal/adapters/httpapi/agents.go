// Package httpapi — the Nexus admin surface.
//
// Agent CRUD + enable/disable. Everything about an agent is editable
// at runtime (avatar, bio, system context, posting rules, consumed
// trend types) — no redeploys, no hardcoded personas.
package httpapi

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

type agentPayload struct {
	Name          string         `json:"name"`
	Avatar        string         `json:"avatar"`
	Bio           string         `json:"bio"`
	Active        *bool          `json:"active"`
	Specialty     string         `json:"specialty"`
	TrendTypes    []string       `json:"trend_types"`
	PostingRules  map[string]any `json:"posting_rules"`
	RAGSources    []string       `json:"rag_sources"`
	SystemContext string         `json:"system_context"`
}

func agentJSON(a agent.Agent) map[string]any {
	return map[string]any{
		"id":             a.ID.String(),
		"name":           a.Name,
		"avatar":         a.Avatar,
		"bio":            a.Bio,
		"active":         a.Active,
		"specialty":      a.Specialty,
		"trend_types":    a.TrendTypes,
		"posting_rules":  a.PostingRules,
		"rag_sources":    a.RAGSources,
		"system_context": a.SystemContext,
		"queue":          a.QueueName(),
		"created_at":     a.CreatedAt.Format(time.RFC3339),
		"updated_at":     a.UpdatedAt.Format(time.RFC3339),
	}
}

// Routes mounts the admin API + health + metrics + audit handlers.
//
// Access model: /live and /metrics are public probes. Every admin route
// requires a Gateway operator session. Nexus introspects the opaque session
// with Insight Gateway and consumes Gateway-issued permissions.
func Routes(
	agents ports.AgentRepository,
	audit AuditDeps,
	pub PublicationDeps,
	consoleOps ConsoleOpsDeps,
	authCfg AuthConfig,
	metricsHandler http.Handler,
	logger zerolog.Logger,
) http.Handler {
	mux := http.NewServeMux()
	mountAudit(mux, audit, logger)
	// Sprint 4 — publication admin endpoints (candidates, tickets,
	// history, provider health, agent metrics). Optional deps: lab
	// boots without the publication engine still serve the rest.
	if pub.Candidates != nil && pub.Tickets != nil && pub.Health != nil {
		RegisterPublicationRoutes(mux, pub.Candidates, pub.Tickets, pub.Health)
	}
	// Sprint 4.5 — Console mutation surface (ticket review, manual
	// publication, personas, immutable audit log) + V1.1 DLQ ops.
	if consoleOps.Tickets != nil && consoleOps.Audit != nil {
		consoleOps.Logger = logger
		RegisterConsoleOps(mux, consoleOps)
	}

	mux.HandleFunc("GET /v1/agents", func(w http.ResponseWriter, r *http.Request) {
		list, err := agents.List(r.Context())
		if err != nil {
			httpError(w, logger, err)
			return
		}
		out := make([]map[string]any, 0, len(list))
		for _, a := range list {
			out = append(out, agentJSON(a))
		}
		writeJSON(w, http.StatusOK, map[string]any{"agents": out})
	})

	mux.HandleFunc("GET /v1/agents/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid id"})
			return
		}
		a, err := agents.Get(r.Context(), id)
		if err != nil {
			httpError(w, logger, err)
			return
		}
		writeJSON(w, http.StatusOK, agentJSON(a))
	})

	mux.HandleFunc("POST /v1/agents", func(w http.ResponseWriter, r *http.Request) {
		var p agentPayload
		if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		now := time.Now().UTC()
		a := agent.Agent{
			ID:            uuid.New(),
			Name:          p.Name,
			Avatar:        p.Avatar,
			Bio:           p.Bio,
			Active:        p.Active == nil || *p.Active,
			Specialty:     p.Specialty,
			TrendTypes:    p.TrendTypes,
			PostingRules:  p.PostingRules,
			RAGSources:    p.RAGSources,
			SystemContext: p.SystemContext,
			CreatedAt:     now,
			UpdatedAt:     now,
		}
		if err := a.Validate(); err != nil {
			writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"error": err.Error()})
			return
		}
		if err := agents.Create(r.Context(), a); err != nil {
			httpError(w, logger, err)
			return
		}
		writeJSON(w, http.StatusCreated, agentJSON(a))
	})

	mux.HandleFunc("PUT /v1/agents/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid id"})
			return
		}
		existing, err := agents.Get(r.Context(), id)
		if err != nil {
			httpError(w, logger, err)
			return
		}
		var p agentPayload
		if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		applyPayload(&existing, p)
		existing.UpdatedAt = time.Now().UTC()
		if err := existing.Validate(); err != nil {
			writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"error": err.Error()})
			return
		}
		if err := agents.Update(r.Context(), existing); err != nil {
			httpError(w, logger, err)
			return
		}
		writeJSON(w, http.StatusOK, agentJSON(existing))
	})

	mux.HandleFunc("POST /v1/agents/{id}/enable", setActiveHandler(agents, logger, true))
	mux.HandleFunc("POST /v1/agents/{id}/disable", setActiveHandler(agents, logger, false))

	// Public probes stay outside the auth wrapper; every admin route
	// (the whole mux above) sits behind it.
	root := http.NewServeMux()
	root.HandleFunc("GET /live", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	root.Handle("GET /metrics", metricsHandler)
	root.Handle("/", RequireAuth(authCfg, mux))
	return root
}

// applyPayload — partial update semantics: only supplied fields change.
func applyPayload(a *agent.Agent, p agentPayload) {
	if p.Name != "" {
		a.Name = p.Name
	}
	if p.Avatar != "" {
		a.Avatar = p.Avatar
	}
	if p.Bio != "" {
		a.Bio = p.Bio
	}
	if p.Specialty != "" {
		a.Specialty = p.Specialty
	}
	if p.TrendTypes != nil {
		a.TrendTypes = p.TrendTypes
	}
	if p.PostingRules != nil {
		a.PostingRules = p.PostingRules
	}
	if p.RAGSources != nil {
		a.RAGSources = p.RAGSources
	}
	if p.SystemContext != "" {
		a.SystemContext = p.SystemContext
	}
	if p.Active != nil {
		a.Active = *p.Active
	}
}

func setActiveHandler(
	agents ports.AgentRepository, logger zerolog.Logger, active bool,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid id"})
			return
		}
		if err := agents.SetActive(r.Context(), id, active); err != nil {
			httpError(w, logger, err)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"id": id.String(), "active": active})
	}
}

func httpError(w http.ResponseWriter, logger zerolog.Logger, err error) {
	switch {
	case errors.Is(err, ports.ErrNotFound):
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
	case errors.Is(err, ports.ErrDuplicate):
		writeJSON(w, http.StatusConflict, map[string]string{"error": "duplicate"})
	default:
		logger.Error().Err(err).Msg("httpapi_internal_error")
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
	}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
