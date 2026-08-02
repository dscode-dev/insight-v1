package opsadmin

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/google/uuid"

	appmod "github.com/konoha-labs/insight-gateway/internal/application/moderation"
	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

const maxResponseBody = 1 << 20

type SessionRevoker interface {
	RevokeAllForUser(context.Context, uuid.UUID) (int64, error)
}

type Handlers struct {
	token         string
	sportHubURL   string
	sportHubToken string
	revoker       SessionRevoker
	client        *http.Client
	moderation    Moderation
	agentState    AgentStateSetter
}

type Moderation interface {
	Act(context.Context, appmod.ActInput) error
	IsContentHidden(context.Context, dommod.TargetType, string) (bool, error)
}

type AgentStateSetter func(context.Context, string, string, string, string, string) error

func New(token, sportHubURL, sportHubToken string, revoker SessionRevoker) (*Handlers, error) {
	sportHubURL = strings.TrimRight(strings.TrimSpace(sportHubURL), "/")
	parsed, err := url.ParseRequestURI(sportHubURL)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("invalid SPORT_HUB_HTTP_BASE_URL")
	}
	return &Handlers{
		token: token, sportHubURL: sportHubURL, sportHubToken: sportHubToken, revoker: revoker,
		client: &http.Client{Timeout: 15 * time.Second},
	}, nil
}

func (h *Handlers) WithSocial(moderation Moderation, agentState AgentStateSetter) *Handlers {
	h.moderation = moderation
	h.agentState = agentState
	return h
}

func (h *Handlers) Require(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if h.token == "" {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "gateway_ops_disabled"})
			return
		}
		got := r.Header.Get("X-Ops-Token")
		if got == "" || subtle.ConstantTimeCompare([]byte(got), []byte(h.token)) != 1 {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "invalid_ops_token"})
			return
		}
		next(w, r)
	}
}

func (h *Handlers) RevokeSessions(w http.ResponseWriter, r *http.Request) {
	userID, err := uuid.Parse(r.PathValue("id"))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_user_id"})
		return
	}
	count, err := h.revoker.RevokeAllForUser(r.Context(), userID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "session_revoke_failed"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status": "revoked", "user_id": userID.String(), "revoked_sessions": count,
		"operator_id":    r.Header.Get("X-Operator"),
		"correlation_id": r.Header.Get("X-Correlation-ID"),
	})
}

func (h *Handlers) ReplayDLQ(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimSpace(r.PathValue("id"))
	if _, err := uuid.Parse(id); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_dlq_id"})
		return
	}
	req, err := http.NewRequestWithContext(
		r.Context(), http.MethodPost,
		h.sportHubURL+"/v1/dlq/"+url.PathEscape(id)+"/replay", nil,
	)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "dlq_replay_request_failed"})
		return
	}
	req.Header.Set("X-Operator", r.Header.Get("X-Operator"))
	req.Header.Set("X-Ops-Token", h.sportHubToken)
	req.Header.Set("X-Correlation-ID", r.Header.Get("X-Correlation-ID"))
	req.Header.Set("Idempotency-Key", r.Header.Get("Idempotency-Key"))
	response, err := h.client.Do(req)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"detail": "sport_hub_unreachable"})
		return
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(response.Body, maxResponseBody))
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		writeJSON(w, http.StatusBadGateway, map[string]any{
			"detail": "sport_hub_dlq_replay_failed", "upstream_status": response.StatusCode,
		})
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

func (h *Handlers) ListDLQ(w http.ResponseWriter, r *http.Request) {
	query := url.Values{}
	for _, key := range []string{"provider", "failure_type", "unreplayed", "limit", "offset"} {
		if value := strings.TrimSpace(r.URL.Query().Get(key)); value != "" {
			query.Set(key, value)
		}
	}
	req, err := http.NewRequestWithContext(
		r.Context(), http.MethodGet, h.sportHubURL+"/v1/dlq?"+query.Encode(), nil,
	)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "dlq_list_request_failed"})
		return
	}
	req.Header.Set("X-Ops-Token", h.sportHubToken)
	response, err := h.client.Do(req)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"detail": "sport_hub_unreachable"})
		return
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(response.Body, maxResponseBody))
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		writeJSON(w, http.StatusBadGateway, map[string]any{
			"detail": "sport_hub_dlq_list_failed", "upstream_status": response.StatusCode,
		})
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

func (h *Handlers) AgentState(w http.ResponseWriter, r *http.Request) {
	if h.agentState == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "social_agent_state_unconfigured"})
		return
	}
	id := r.PathValue("id")
	if _, err := uuid.Parse(id); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_agent_id"})
		return
	}
	action := r.PathValue("action")
	if action != "deactivate" && action != "reactivate" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_agent_action"})
		return
	}
	var body struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&body)
	err := h.agentState(
		r.Context(), id, action, strings.TrimSpace(body.Reason),
		r.Header.Get("X-Operator"), r.Header.Get("X-Correlation-ID"),
	)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"detail": "social_agent_state_failed"})
		return
	}
	state := map[string]string{"deactivate": "inactive", "reactivate": "active"}[action]
	writeJSON(w, http.StatusOK, map[string]any{"agent_id": id, "resulting_state": state})
}

func (h *Handlers) ContentState(w http.ResponseWriter, r *http.Request) {
	if h.moderation == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "moderation_unconfigured"})
		return
	}
	id := r.PathValue("id")
	if _, err := uuid.Parse(id); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_content_id"})
		return
	}
	targetType := dommod.TargetType(r.PathValue("type"))
	if targetType != dommod.TargetPost && targetType != dommod.TargetComment {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_content_type"})
		return
	}
	verb := r.PathValue("action")
	action := dommod.ActionRemove
	if verb == "restore" {
		action = dommod.ActionRestore
	} else if verb != "hide" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_content_action"})
		return
	}
	var body struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<10)).Decode(&body)
	err := h.moderation.Act(r.Context(), appmod.ActInput{
		ModeratorID: r.Header.Get("X-Operator"), Action: string(action),
		TargetType: string(targetType), TargetID: id, Note: strings.TrimSpace(body.Reason),
	})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "content_state_failed"})
		return
	}
	hidden, err := h.moderation.IsContentHidden(r.Context(), targetType, id)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "content_state_verify_failed"})
		return
	}
	state := "visible"
	if hidden {
		state = "hidden"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"content_id": id, "content_type": string(targetType), "resulting_state": state,
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
