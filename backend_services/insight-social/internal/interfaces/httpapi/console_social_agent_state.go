// CONSOLE-SOCIAL-B — agent operational-state mutation (internal Social HTTP).
//
// The internal Social HTTP port is gateway-only. The Gateway operator command
// plane (console_social_intervention) authorizes the operator, records canonical
// audit, and forwards the SERVER-DERIVED operator id + correlation id here. This
// handler is the write path for agent_profiles.active + durable history; the
// publication choke point (post.Service.Create) is what actually enforces it.

package httpapi

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"net/http"

	"github.com/google/uuid"

	domagent "github.com/konoha-labs/insight-social/internal/domain/agent"
)

// AgentStateStore is the persistence surface for agent operational state
// (satisfied by *agentrepo.Repository).
type AgentStateStore interface {
	SetActive(ctx context.Context, id uuid.UUID, active bool, reason, operatorID, correlationID string) (bool, error)
}

type agentStateBody struct {
	Reason        string `json:"reason"`
	OperatorID    string `json:"operator_id"`
	CorrelationID string `json:"correlation_id"`
}

// ConsoleSocialAgentState toggles an agent's operational state. active=false
// (deactivate) / active=true (reactivate). Idempotent, durable history.
func ConsoleSocialAgentState(store AgentStateStore, active bool, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if token == "" {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"detail": "social_ops_disabled"})
			return
		}
		got := r.Header.Get("X-Ops-Token")
		if got == "" || subtle.ConstantTimeCompare([]byte(got), []byte(token)) != 1 {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "invalid_ops_token"})
			return
		}
		id := r.PathValue("id")
		if !isUUID(id) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_agent_id"})
			return
		}
		aid, err := uuid.Parse(id)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_agent_id"})
			return
		}
		var body agentStateBody
		if r.Body != nil {
			_ = json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&body)
		}
		if body.OperatorID == "" {
			// Internal caller (gateway) must attribute the operator; fail-closed.
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "operator_id_required"})
			return
		}
		resulting, serr := store.SetActive(r.Context(), aid, active, body.Reason, body.OperatorID, body.CorrelationID)
		if serr != nil {
			if errors.Is(serr, domagent.ErrNotFound) {
				writeJSON(w, http.StatusNotFound, map[string]any{"detail": "agent_not_found"})
				return
			}
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "agent_state_update_failed"})
			return
		}
		state := "active"
		if !resulting {
			state = "inactive"
		}
		writeJSON(w, http.StatusOK, map[string]any{"agent_id": id, "resulting_state": state})
	}
}
