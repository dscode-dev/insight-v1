// Publication admin API — Sprint 4 Part 16. Internal/admin-only (the
// Nexus HTTP listener is never public; the Console reaches it through
// the internal network).
package httpapi

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/konoha-labs/insight-nexus/internal/application/llmrouter"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// PublicationDeps — the Sprint 4 admin API dependencies (all
// optional; nil disables the routes).
type PublicationDeps struct {
	Candidates ports.CandidateRepository
	Tickets    ports.TicketRepository
	Health     *llmrouter.HealthManager
}

// RegisterPublicationRoutes mounts the Sprint 4 admin endpoints.
func RegisterPublicationRoutes(
	mux *http.ServeMux,
	candidates ports.CandidateRepository,
	tickets ports.TicketRepository,
	health *llmrouter.HealthManager,
) {
	// GET /v1/publications/candidates?status=&limit=
	mux.HandleFunc("GET /v1/publications/candidates", func(w http.ResponseWriter, r *http.Request) {
		status := publication.CandidateStatus(r.URL.Query().Get("status"))
		out, err := candidates.List(r.Context(), status, pubLimit(r, 50))
		if err != nil {
			pubError(w, err)
			return
		}
		pubJSON(w, map[string]any{"candidates": out})
	})

	// GET /v1/publications/history — published posts, newest first.
	mux.HandleFunc("GET /v1/publications/history", func(w http.ResponseWriter, r *http.Request) {
		out, err := candidates.History(r.Context(), pubLimit(r, 50))
		if err != nil {
			pubError(w, err)
			return
		}
		pubJSON(w, map[string]any{"published": out})
	})

	// GET /v1/publications/tickets?status=&limit=
	mux.HandleFunc("GET /v1/publications/tickets", func(w http.ResponseWriter, r *http.Request) {
		status := publication.TicketStatus(r.URL.Query().Get("status"))
		out, err := tickets.List(r.Context(), status, pubLimit(r, 50))
		if err != nil {
			pubError(w, err)
			return
		}
		pubJSON(w, map[string]any{"tickets": out})
	})

	// GET /v1/llm/health — provider routing statuses.
	mux.HandleFunc("GET /v1/llm/health", func(w http.ResponseWriter, r *http.Request) {
		pubJSON(w, map[string]any{"providers": health.Snapshots()})
	})

	// GET /v1/publications/agent-metrics — per-agent outcome counts.
	mux.HandleFunc("GET /v1/publications/agent-metrics", func(w http.ResponseWriter, r *http.Request) {
		counts, err := candidates.AgentCounts(r.Context())
		if err != nil {
			pubError(w, err)
			return
		}
		pubJSON(w, map[string]any{"agents": counts})
	})
}

func pubLimit(r *http.Request, fallback int) int {
	raw := r.URL.Query().Get("limit")
	if raw == "" {
		return fallback
	}
	v, err := strconv.Atoi(raw)
	if err != nil || v <= 0 {
		return fallback
	}
	if v > 200 {
		return 200
	}
	return v
}

func pubError(w http.ResponseWriter, err error) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusInternalServerError)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
}

func pubJSON(w http.ResponseWriter, body any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(body)
}
