// CONSOLE-SOCIAL-B — enforcement-state read model (operator-authed).
//
// Surfaces the CURRENT enforcement state + recent action history for a target so
// an operator sees real state (not a decorative flag) before/after intervening.
// Reuses the moderation service for current state; reads moderation_actions for
// history. Read-only; operator-session gated.

package console

import (
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

// SocialEnforcementState serves GET /v1/console/social/enforcement/{type}/{id}.
// type ∈ user|post|comment. Returns current state + recent moderation actions.
func (h *Handlers) SocialEnforcementState(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireOperator(w, r); !ok {
		return
	}
	if h.mod == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"detail": "enforcement_unconfigured"})
		return
	}
	targetType := chi.URLParam(r, "type")
	targetID := chi.URLParam(r, "id")
	switch targetType {
	case "user", "post", "comment":
	default:
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_target_type"})
		return
	}

	out := map[string]any{
		"target": map[string]any{"type": targetType, "id": targetID},
	}

	if targetType == "user" {
		uid, err := uuid.Parse(targetID)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_user_id"})
			return
		}
		state, until, serr := h.mod.UserState(r.Context(), uid)
		if serr != nil {
			out["state"] = "unknown"
		} else {
			out["state"] = string(state)
			if until != nil {
				out["expires_at"] = until.UTC().Format(time.RFC3339)
			}
		}
	} else {
		hidden, herr := h.mod.IsContentHidden(r.Context(), dommod.TargetType(targetType), targetID)
		if herr != nil {
			out["state"] = "unknown"
		} else if hidden {
			out["state"] = "hidden"
		} else {
			out["state"] = "visible"
		}
	}

	// Recent action history for this target (durable moderation_actions).
	history := []map[string]any{}
	rows, err := h.db.Query(r.Context(), `
SELECT action, moderator_id, COALESCE(note,''), created_at, COALESCE(report_id::text,'')
  FROM moderation_actions
 WHERE target_type = $1 AND target_id = $2
 ORDER BY created_at DESC
 LIMIT 25`, targetType, targetID)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var action, moderatorID, note, reportID string
			var createdAt time.Time
			if err := rows.Scan(&action, &moderatorID, &note, &createdAt, &reportID); err != nil {
				continue
			}
			item := map[string]any{
				"action": action, "operator_id": moderatorID, "note": note,
				"occurred_at": createdAt.UTC().Format(time.RFC3339),
			}
			if reportID != "" {
				item["report_id"] = reportID
			}
			history = append(history, item)
		}
	}
	out["history"] = history
	writeJSON(w, http.StatusOK, out)
}
