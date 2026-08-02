// CONSOLE-SOCIAL-B — per-action intervention handlers + audit/correlation helpers.
// Each handler is a thin, explicit command: decode → begin(authorize+intent) →
// domain mutation (+ optional session revoke) → verify → finish(outcome+response).

package console

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	appmod "github.com/konoha-labs/insight-gateway/internal/application/moderation"
	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

// correlationID derives a stable per-command correlation id (reuses the inbound
// request id when present so the browser→BFF→gateway chain shares one id).
func correlationID(r *http.Request) string {
	if rid := r.Header.Get("X-Request-Id"); rid != "" {
		return clip(rid, 128)
	}
	return uuid.NewString()
}

// recordAudit writes one canonical administrative audit row (SECURITY-A1 spine).
// Idempotent per (correlation_id, status). Returns an error so callers can
// fail-closed on the pre-mutation INTENT record.
func (h *Handlers) recordAudit(ctx context.Context, cc cmdContext, status, decision, reasonCode string) error {
	meta := map[string]any{}
	if cc.reason != "" {
		meta["reason"] = clip(cc.reason, 512)
	}
	if cc.reportID != "" {
		meta["report_id"] = cc.reportID
	}
	metaJSON, err := json.Marshal(meta)
	if err != nil {
		return err
	}
	nz := func(s string, n int) any {
		s = clip(s, n)
		if s == "" {
			return nil
		}
		return s
	}
	idem := cc.correlationID + ":" + status
	_, err = h.db.Exec(ctx, `
INSERT INTO operator_audit_log (
  operator_id, event_type, request_id, metadata,
  capability, correlation_id, session_id, target_environment, target_service,
  target_resource_type, target_resource_id, authz_decision, authz_reason_code,
  outcome_status, idempotency_key, source
) VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING`,
		cc.operatorID, clip(cc.capability, 128), nz(cc.correlationID, 128), string(metaJSON),
		clip(cc.capability, 128), nz(cc.correlationID, 128), cc.sessionKey,
		nil, "insight-social",
		nz(cc.targetType, 64), nz(cc.targetID, 200), decision, clip(reasonCode, 64),
		status, clip(idem, 200), "insight-console",
	)
	return err
}

// act runs a reused moderation Act with the SERVER-derived operator id as the
// moderator (never a client value).
func (h *Handlers) act(ctx context.Context, cc cmdContext, action string, suspendDays int) error {
	return h.mod.Act(ctx, appmod.ActInput{
		ModeratorID: cc.operatorID,
		Action:      action,
		ReportID:    cc.reportID,
		TargetType:  cc.targetType,
		TargetID:    cc.targetID,
		Note:        cc.reason,
		SuspendDays: suspendDays,
	})
}

// ---- USER: suspend / unsuspend / ban / unban ----

func (h *Handlers) SocialSuspendUser(w http.ResponseWriter, r *http.Request) {
	h.userCmd(w, r, "social.user.suspend", "suspend")
}
func (h *Handlers) SocialUnsuspendUser(w http.ResponseWriter, r *http.Request) {
	h.userCmd(w, r, "social.user.suspend", "unsuspend")
}
func (h *Handlers) SocialBanUser(w http.ResponseWriter, r *http.Request) {
	h.userCmd(w, r, "social.user.ban", "ban")
}
func (h *Handlers) SocialUnbanUser(w http.ResponseWriter, r *http.Request) {
	h.userCmd(w, r, "social.user.ban", "unban")
}

func (h *Handlers) userCmd(w http.ResponseWriter, r *http.Request, capability, op string) {
	id := chi.URLParam(r, "id")
	uid, err := uuid.Parse(id)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_user_id"})
		return
	}
	body, ok := h.decodeIntervention(w, r)
	if !ok {
		return
	}
	cc, ok := h.begin(w, r, capability, "user", uid.String(), body)
	if !ok {
		return
	}

	var mutErr error
	switch op {
	case "suspend":
		mutErr = h.act(r.Context(), cc, string(dommod.ActionSuspendUser), body.SuspendDays)
		if mutErr == nil && h.revoker != nil {
			_, _ = h.revoker.RevokeAllForUser(r.Context(), uid) // force logout (best-effort; write-gate is authoritative)
		}
	case "ban":
		mutErr = h.act(r.Context(), cc, string(dommod.ActionBanUser), 0)
		if mutErr == nil && h.revoker != nil {
			_, _ = h.revoker.RevokeAllForUser(r.Context(), uid)
		}
	case "unsuspend", "unban":
		mutErr = h.act(r.Context(), cc, string(dommod.ActionRestoreUser), 0)
	}
	if h.mapMutErr(w, r, cc, mutErr) {
		return
	}

	// Verify post-condition.
	state, until, verr := h.mod.UserState(r.Context(), uid)
	resulting := map[string]any{"resulting_state": stateStr(state, verr)}
	if until != nil {
		resulting["expires_at"] = until.UTC().Format(time.RFC3339)
	}
	h.finish(w, r, cc, resulting, nil)
}

func stateStr(s dommod.UserState, err error) string {
	if err != nil {
		return "unknown"
	}
	return string(s)
}

// ---- CONTENT: hide / restore (post, comment) ----

func (h *Handlers) SocialHidePost(w http.ResponseWriter, r *http.Request) {
	h.contentCmd(w, r, "social.content.hide", "post", true)
}
func (h *Handlers) SocialRestorePost(w http.ResponseWriter, r *http.Request) {
	h.contentCmd(w, r, "social.content.restore", "post", false)
}
func (h *Handlers) SocialHideComment(w http.ResponseWriter, r *http.Request) {
	h.contentCmd(w, r, "social.content.hide", "comment", true)
}
func (h *Handlers) SocialRestoreComment(w http.ResponseWriter, r *http.Request) {
	h.contentCmd(w, r, "social.content.restore", "comment", false)
}

func (h *Handlers) contentCmd(w http.ResponseWriter, r *http.Request, capability, targetType string, hide bool) {
	id := chi.URLParam(r, "id")
	if _, err := uuid.Parse(id); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_content_id"})
		return
	}
	body, ok := h.decodeIntervention(w, r)
	if !ok {
		return
	}
	cc, ok := h.begin(w, r, capability, targetType, id, body)
	if !ok {
		return
	}
	action := string(dommod.ActionRestore)
	if hide {
		action = string(dommod.ActionRemove)
	}
	mutErr := h.act(r.Context(), cc, action, 0)
	if h.mapMutErr(w, r, cc, mutErr) {
		return
	}
	hidden, verr := h.mod.IsContentHidden(r.Context(), dommod.TargetType(targetType), id)
	resulting := map[string]any{"resulting_state": hiddenStr(hidden, verr)}
	h.finish(w, r, cc, resulting, nil)
}

func hiddenStr(hidden bool, err error) string {
	if err != nil {
		return "unknown"
	}
	if hidden {
		return "hidden"
	}
	return "visible"
}

// ---- REPORT: review / resolve / dismiss ----

func (h *Handlers) SocialReviewReport(w http.ResponseWriter, r *http.Request) {
	h.reportCmd(w, r, "trust.report.review", dommod.StatusReviewing)
}
func (h *Handlers) SocialResolveReport(w http.ResponseWriter, r *http.Request) {
	h.reportCmd(w, r, "trust.report.resolve", dommod.StatusResolved)
}
func (h *Handlers) SocialDismissReport(w http.ResponseWriter, r *http.Request) {
	h.reportCmd(w, r, "trust.report.dismiss", dommod.StatusDismissed)
}

func (h *Handlers) reportCmd(w http.ResponseWriter, r *http.Request, capability string, to dommod.Status) {
	id := chi.URLParam(r, "id")
	rid, err := uuid.Parse(id)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_report_id"})
		return
	}
	body, ok := h.decodeIntervention(w, r)
	if !ok {
		return
	}
	cc, ok := h.begin(w, r, capability, "report", rid.String(), body)
	if !ok {
		return
	}
	mutErr := h.mod.TransitionReport(r.Context(), rid, to)
	if h.mapMutErr(w, r, cc, mutErr) {
		return
	}
	resulting := map[string]any{"resulting_state": string(to)}
	h.finish(w, r, cc, resulting, nil)
}

// ---- AGENT: deactivate / reactivate (Social-owned state) ----

func (h *Handlers) SocialDeactivateAgent(w http.ResponseWriter, r *http.Request) {
	h.agentCmd(w, r, "social.agent.deactivate", "deactivate")
}
func (h *Handlers) SocialReactivateAgent(w http.ResponseWriter, r *http.Request) {
	h.agentCmd(w, r, "social.agent.reactivate", "reactivate")
}

func (h *Handlers) agentCmd(w http.ResponseWriter, r *http.Request, capability, op string) {
	if h.setAgentState == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "enforcement_unconfigured"})
		return
	}
	id := chi.URLParam(r, "id")
	if _, err := uuid.Parse(id); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_agent_id"})
		return
	}
	body, ok := h.decodeIntervention(w, r)
	if !ok {
		return
	}
	cc, ok := h.begin(w, r, capability, "agent", id, body)
	if !ok {
		return
	}
	mutErr := h.setAgentState(r.Context(), id, op, cc.reason, cc.operatorID, cc.correlationID)
	if h.mapMutErr(w, r, cc, mutErr) {
		return
	}
	resulting := map[string]any{"resulting_state": map[string]string{"deactivate": "inactive", "reactivate": "active"}[op]}
	h.finish(w, r, cc, resulting, nil)
}
