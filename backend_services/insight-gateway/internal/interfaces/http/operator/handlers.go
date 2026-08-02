package operator

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/rs/zerolog"
)

const sessionTTL = 8 * time.Hour

type Handlers struct {
	db *pgxpool.Pool
}

func NewHandlers(db *pgxpool.Pool) *Handlers {
	return &Handlers{db: db}
}

type operatorRow struct {
	ID       uuid.UUID `json:"id"`
	Username string    `json:"username"`
	Email    string    `json:"email"`
	Role     string    `json:"role"`
}

type loginRequest struct {
	Identifier string `json:"identifier"`
	Password   string `json:"password"`
}

type loginResponse struct {
	SessionToken string      `json:"session_token"`
	ExpiresAt    time.Time   `json:"expires_at"`
	Operator     operatorDTO `json:"operator"`
}

type operatorDTO struct {
	ID          string   `json:"id"`
	Username    string   `json:"username"`
	Email       string   `json:"email"`
	DisplayName string   `json:"display_name"`
	Role        string   `json:"role"`
	Permissions []string `json:"permissions"`
}

func (h *Handlers) Login(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid_body")
		return
	}
	req.Identifier = strings.TrimSpace(req.Identifier)
	if req.Identifier == "" || req.Password == "" {
		writeErr(w, http.StatusBadRequest, "invalid_credentials")
		return
	}
	op, ok, err := h.verifyCredentials(r.Context(), req.Identifier, req.Password)
	if err != nil {
		zerolog.Ctx(r.Context()).Error().Err(err).Msg("operator_login_failed")
		writeErr(w, http.StatusServiceUnavailable, "auth_unavailable")
		return
	}
	if !ok {
		_ = h.audit(r.Context(), uuid.Nil, "operator_login_failed", map[string]any{
			"identifier": req.Identifier,
		})
		writeErr(w, http.StatusUnauthorized, "invalid_credentials")
		return
	}
	token, err := newSessionToken()
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "session_issue_failed")
		return
	}
	expires := time.Now().UTC().Add(sessionTTL)
	if err := h.createSession(r.Context(), op.ID, token, expires); err != nil {
		zerolog.Ctx(r.Context()).Error().Err(err).Msg("operator_session_create_failed")
		writeErr(w, http.StatusInternalServerError, "session_issue_failed")
		return
	}
	_ = h.audit(r.Context(), op.ID, "operator_login", nil)
	writeJSON(w, http.StatusOK, loginResponse{
		SessionToken: token,
		ExpiresAt:    expires,
		Operator:     toDTO(op),
	})
}

func (h *Handlers) Me(w http.ResponseWriter, r *http.Request) {
	op, token, ok := h.requireSession(w, r)
	if !ok {
		return
	}
	_ = h.touchSession(r.Context(), token)
	writeJSON(w, http.StatusOK, map[string]any{"operator": toDTO(op)})
}

func (h *Handlers) Refresh(w http.ResponseWriter, r *http.Request) {
	op, token, ok := h.requireSession(w, r)
	if !ok {
		return
	}
	expires := time.Now().UTC().Add(sessionTTL)
	if err := h.extendSession(r.Context(), token, expires); err != nil {
		writeErr(w, http.StatusInternalServerError, "session_refresh_failed")
		return
	}
	_ = h.audit(r.Context(), op.ID, "operator_session_refresh", nil)
	writeJSON(w, http.StatusOK, map[string]any{
		"session_token": token,
		"expires_at":    expires,
		"operator":      toDTO(op),
	})
}

func (h *Handlers) Logout(w http.ResponseWriter, r *http.Request) {
	op, token, ok := h.requireSession(w, r)
	if !ok {
		return
	}
	_ = h.revokeSession(r.Context(), token)
	_ = h.audit(r.Context(), op.ID, "operator_logout", nil)
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handlers) verifyCredentials(ctx context.Context, identifier, password string) (operatorRow, bool, error) {
	var op operatorRow
	err := h.db.QueryRow(ctx, `
SELECT id, username, email, role
  FROM operators
 WHERE (username = $1 OR email = $1)
   AND is_active = TRUE
   AND password_hash = crypt($2, password_hash)
 LIMIT 1`, identifier, password).Scan(&op.ID, &op.Username, &op.Email, &op.Role)
	if err == nil {
		return op, true, nil
	}
	if err == pgx.ErrNoRows {
		return operatorRow{}, false, nil
	}
	return operatorRow{}, false, err
}

func (h *Handlers) requireSession(w http.ResponseWriter, r *http.Request) (operatorRow, string, bool) {
	token := bearer(r)
	if token == "" {
		writeErr(w, http.StatusUnauthorized, "missing_operator_session")
		return operatorRow{}, "", false
	}
	var op operatorRow
	err := h.db.QueryRow(r.Context(), `
SELECT o.id, o.username, o.email, o.role
  FROM operator_sessions s
  JOIN operators o ON o.id = s.operator_id
 WHERE s.token_hash = $1
   AND s.revoked_at IS NULL
   AND s.expires_at > now()
   AND o.is_active = TRUE
 LIMIT 1`, tokenHash(token)).Scan(&op.ID, &op.Username, &op.Email, &op.Role)
	if err != nil {
		writeErr(w, http.StatusUnauthorized, "invalid_operator_session")
		return operatorRow{}, "", false
	}
	return op, token, true
}

func (h *Handlers) createSession(ctx context.Context, operatorID uuid.UUID, token string, expires time.Time) error {
	_, err := h.db.Exec(ctx, `
INSERT INTO operator_sessions (operator_id, token_hash, expires_at)
VALUES ($1, $2, $3)`, operatorID, tokenHash(token), expires)
	return err
}

func (h *Handlers) touchSession(ctx context.Context, token string) error {
	_, err := h.db.Exec(ctx, `UPDATE operator_sessions SET last_seen_at = now() WHERE token_hash = $1`, tokenHash(token))
	return err
}

func (h *Handlers) extendSession(ctx context.Context, token string, expires time.Time) error {
	_, err := h.db.Exec(ctx, `UPDATE operator_sessions SET expires_at = $2, last_seen_at = now() WHERE token_hash = $1`, tokenHash(token), expires)
	return err
}

func (h *Handlers) revokeSession(ctx context.Context, token string) error {
	_, err := h.db.Exec(ctx, `UPDATE operator_sessions SET revoked_at = COALESCE(revoked_at, now()) WHERE token_hash = $1`, tokenHash(token))
	return err
}

func (h *Handlers) audit(ctx context.Context, operatorID uuid.UUID, event string, meta map[string]any) error {
	if meta == nil {
		meta = map[string]any{}
	}
	raw, _ := json.Marshal(meta)
	var id any
	if operatorID != uuid.Nil {
		id = operatorID
	}
	_, err := h.db.Exec(ctx, `
INSERT INTO operator_audit_log (operator_id, event_type, metadata)
VALUES ($1, $2, $3::jsonb)`, id, event, string(raw))
	return err
}

func newSessionToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

func tokenHash(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

func bearer(r *http.Request) string {
	raw := r.Header.Get("Authorization")
	if len(raw) < 8 || !strings.EqualFold(raw[:7], "Bearer ") {
		return ""
	}
	return strings.TrimSpace(raw[7:])
}

func toDTO(op operatorRow) operatorDTO {
	role := normalizeRole(op.Role)
	return operatorDTO{
		ID:          op.ID.String(),
		Username:    op.Username,
		Email:       op.Email,
		DisplayName: op.Username,
		Role:        role,
		Permissions: permissionsForRole(role),
	}
}

func normalizeRole(role string) string {
	switch role {
	case "super_admin", "SuperAdmin", "PlatformAdmin":
		return "SuperAdmin"
	case "admin", "Operations":
		return "Operations"
	case "operator", "Support":
		return "Support"
	case "analyst", "Analyst":
		return "Analyst"
	default:
		return "ReadOnly"
	}
}

func permissionsForRole(role string) []string {
	read := []string{"console.access", "feed.read", "user.read", "model.read", "dlq.read", "audit.read", "flag.read", "config.read", "scheduler.read"}
	switch role {
	case "SuperAdmin":
		return append([]string{"incident.manage"}, []string{"user.read", "user.suspend", "user.ban", "user.shadow_ban", "user.force_logout", "user.invalidate_sessions", "user.change_permissions", "user.flag_for_audit", "user.add_notes", "feed.read", "feed.hide", "feed.delete", "feed.restore", "feed.mark_sensitive", "scheduler.read", "scheduler.pause", "scheduler.resume", "scheduler.force_sync", "provider.read", "provider.enable", "provider.disable", "provider.maintenance", "provider.force_sync", "model.read", "model.promote", "model.rollback", "model.pause_consumer", "model.resume_consumer", "model.enable_family", "model.disable_family", "model.clear_cache", "dlq.read", "dlq.replay", "dlq.archive", "dlq.mark_resolved", "audit.read", "flag.read", "flag.write", "config.read", "config.write", "maintenance_mode.toggle", "console.access"}...)
	case "Operations":
		return append(read, "incident.manage", "scheduler.pause", "scheduler.resume", "scheduler.force_sync", "provider.enable", "provider.disable", "dlq.replay")
	case "Support":
		return append(read, "user.add_notes", "user.flag_for_audit")
	default:
		return read
	}
}

func writeErr(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if status != http.StatusNoContent {
		_ = json.NewEncoder(w).Encode(v)
	}
}
