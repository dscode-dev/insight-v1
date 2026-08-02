// CONSOLE-SOCIAL-B — Social Enforcement Plane (operator-driven interventions).
//
// Typed, per-action administrative commands over the EXISTING Gateway-owned
// enforcement state (moderation_user_state / moderation_hidden_content /
// moderation_reports) plus Social-owned agent operational state. Every command:
//
//  1. requires a VERIFIED operator session (identity derived server-side; the
//     request body can never assert operator_id / moderator_id / actor);
//  2. authorizes the EXACT capability's permission (fail-closed) from the
//     operator's role — capability presence never grants a right;
//  3. records durable canonical audit INTENT (SECURITY-A1 operator_audit_log)
//     BEFORE the mutation — high-impact actions fail closed if intent cannot be
//     recorded;
//  4. performs the domain mutation through the existing enforcement service
//     (reuse, not a parallel decorative store) — ban/suspend also revoke the
//     user's live sessions;
//  5. records the canonical audit OUTCOME (COMPLETED / FAILED);
//  6. verifies + returns the resulting state.
//
// Read-only guarantees are unchanged elsewhere; this is the ONLY mutating console
// surface, and it maps to real enforcement (see CONSOLE_SOCIAL_B_ENFORCEMENT_AUDIT).

package console

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"

	appmod "github.com/konoha-labs/insight-gateway/internal/application/moderation"
	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

const maxInterventionBody = 8 * 1024 // 8 KiB

// moderationPort is the narrow enforcement surface the intervention handlers use
// (satisfied by *moderation.Service; an interface keeps this testable).
type moderationPort interface {
	Act(ctx context.Context, in appmod.ActInput) error
	TransitionReport(ctx context.Context, id uuid.UUID, to dommod.Status) error
	GetReport(ctx context.Context, id uuid.UUID) (*dommod.Report, error)
	UserState(ctx context.Context, userID uuid.UUID) (dommod.UserState, *time.Time, error)
	IsContentHidden(ctx context.Context, t dommod.TargetType, id string) (bool, error)
}

// sessionRevoker force-logs-out a user's live end-user sessions (ban/suspend).
type sessionRevoker interface {
	RevokeAllForUser(ctx context.Context, userID uuid.UUID) (int64, error)
}

// agentStateSetter toggles Social-owned agent operational state (deactivate /
// reactivate) through the internal Social HTTP mutation endpoint.
type agentStateSetter func(ctx context.Context, agentID, action, reason, operatorID, correlationID string) error

// WithEnforcement wires the SOCIAL-B enforcement dependencies onto the console
// handlers. Called once at startup after the moderation service + session repo
// exist. When any is nil the corresponding command returns 503 (fail-closed).
func (h *Handlers) WithEnforcement(mod moderationPort, revoker sessionRevoker, agent agentStateSetter) *Handlers {
	h.mod = mod
	h.revoker = revoker
	h.setAgentState = agent
	return h
}

// capPermission maps each SOCIAL-B capability to the operator permission it
// requires. Fail-closed: an unmapped capability is never authorized.
var capPermission = map[string]string{
	"social.user.suspend":     "user.suspend",
	"social.user.ban":         "user.ban",
	"social.content.hide":     "feed.hide",
	"social.content.restore":  "feed.restore",
	"social.agent.deactivate": "feed.hide",
	"social.agent.reactivate": "feed.restore",
	"trust.report.review":     "feed.read",
	"trust.report.resolve":    "feed.hide",
	"trust.report.dismiss":    "feed.hide",
}

// authorizeCap returns true when the operator's role carries the permission the
// capability requires. Registry presence NEVER grants — this is the decision.
func authorizeCap(role, capability string) (permission string, ok bool) {
	permission, mapped := capPermission[capability]
	if !mapped {
		return "", false
	}
	for _, p := range PermissionsForRole(NormalizeRole(role)) {
		if p == permission {
			return permission, true
		}
	}
	return permission, false
}

// interventionBody is the ONLY accepted command payload. Actor identity fields
// are deliberately NOT decoded — operator identity is server-derived. Any
// client-supplied operator_id / moderator_id / actor_id is ignored (stripped).
type interventionBody struct {
	Reason      string `json:"reason"`
	ReportID    string `json:"report_id"`
	SuspendDays int    `json:"suspend_days"`
	// Ignored on purpose (documented): operator_id, moderator_id, actor_id, session_id.
}

func (h *Handlers) decodeIntervention(w http.ResponseWriter, r *http.Request) (interventionBody, bool) {
	var body interventionBody
	r.Body = http.MaxBytesReader(w, r.Body, maxInterventionBody)
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(&body); err != nil && err.Error() != "EOF" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_json"})
		return interventionBody{}, false
	}
	body.Reason = strings.TrimSpace(body.Reason)
	if body.Reason == "" || len(body.Reason) > 512 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "reason_required"})
		return interventionBody{}, false
	}
	if body.SuspendDays < 0 || body.SuspendDays > 3650 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_suspend_days"})
		return interventionBody{}, false
	}
	if body.ReportID != "" {
		if _, err := uuid.Parse(body.ReportID); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_report_id"})
			return interventionBody{}, false
		}
	}
	return body, true
}

// cmdContext carries the authorized command frame through the lifecycle.
type cmdContext struct {
	operatorID    string
	sessionKey    string
	capability    string
	permission    string
	correlationID string
	targetType    string
	targetID      string
	reason        string
	reportID      string
}

// begin authorizes + records intent. On deny it writes 403 (+ DENIED audit) and
// returns ok=false. On an intent-record failure for a high-impact action it
// writes 500 (fail-closed) and returns ok=false — the mutation must NOT run.
func (h *Handlers) begin(w http.ResponseWriter, r *http.Request, capability, targetType, targetID string, body interventionBody) (cmdContext, bool) {
	if h.mod == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "enforcement_unconfigured"})
		return cmdContext{}, false
	}
	operatorID, role, sessionKey, ok := h.requireOperatorFull(w, r)
	if !ok {
		return cmdContext{}, false
	}
	permission, allowed := authorizeCap(role, capability)
	cc := cmdContext{
		operatorID: operatorID, sessionKey: sessionKey, capability: capability,
		permission: permission, correlationID: correlationID(r),
		targetType: targetType, targetID: targetID, reason: body.Reason, reportID: body.ReportID,
	}
	if !allowed {
		_ = h.recordAudit(r.Context(), cc, "DENIED", "deny", "denied_permission_missing")
		writeJSON(w, http.StatusForbidden, map[string]string{"detail": "forbidden_capability"})
		return cmdContext{}, false
	}
	// Durable intent BEFORE mutation. High-impact ⇒ fail closed.
	if err := h.recordAudit(r.Context(), cc, "AUTHORIZED", "allow", "authorized"); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "audit_intent_failed"})
		return cmdContext{}, false
	}
	return cc, true
}

// finish records the outcome + writes the response. resultState/hidden are the
// verified post-condition. err != nil ⇒ FAILED outcome + 502.
func (h *Handlers) finish(w http.ResponseWriter, r *http.Request, cc cmdContext, resulting map[string]any, mutErr error) {
	if mutErr != nil {
		_ = h.recordAudit(r.Context(), cc, "FAILED", "allow", "mutation_failed")
		writeJSON(w, http.StatusBadGateway, map[string]any{"detail": "enforcement_mutation_failed", "correlation_id": cc.correlationID})
		return
	}
	_ = h.recordAudit(r.Context(), cc, "COMPLETED", "allow", "completed")
	out := map[string]any{
		"ok": true, "capability": cc.capability, "correlation_id": cc.correlationID,
		"target": map[string]any{"type": cc.targetType, "id": cc.targetID},
	}
	for k, v := range resulting {
		out[k] = v
	}
	writeJSON(w, http.StatusOK, out)
}

// mapMutErr normalizes known enforcement errors to explicit HTTP responses
// (invalid transition / not found) vs the generic failed path.
func (h *Handlers) mapMutErr(w http.ResponseWriter, r *http.Request, cc cmdContext, err error) bool {
	if err == nil {
		return false
	}
	switch {
	case errors.Is(err, dommod.ErrInvalidTarget):
		_ = h.recordAudit(r.Context(), cc, "FAILED", "allow", "invalid_target")
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_target"})
	case errors.Is(err, dommod.ErrInvalidAction):
		_ = h.recordAudit(r.Context(), cc, "FAILED", "allow", "invalid_transition")
		writeJSON(w, http.StatusConflict, map[string]string{"detail": "invalid_transition"})
	case errors.Is(err, dommod.ErrReportNotFound):
		_ = h.recordAudit(r.Context(), cc, "FAILED", "allow", "not_found")
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "report_not_found"})
	case errors.Is(err, errAgentNotFound):
		_ = h.recordAudit(r.Context(), cc, "FAILED", "allow", "not_found")
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "agent_not_found"})
	default:
		_ = h.recordAudit(r.Context(), cc, "FAILED", "allow", "mutation_failed")
		writeJSON(w, http.StatusBadGateway, map[string]string{"detail": "enforcement_mutation_failed"})
	}
	return true
}
