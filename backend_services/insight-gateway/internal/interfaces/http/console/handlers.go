// Package console implements the read-only operations surface the Insight
// Console consumes for Cloud platform health, the audit log, and user/operator
// administration. Every endpoint is guarded by a valid operator session
// (the same opaque token issued by /v1/operator/auth/login) — the Console BFF
// forwards it as a Bearer. Read-only: no mutations. (CONSOLE-OPS-A2.)
package console

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"google.golang.org/grpc/connectivity"
)

// socialState is the slice of *socialclient.Client the health probe needs.
type socialState interface{ State() connectivity.State }

type Handlers struct {
	db            *pgxpool.Pool
	rdb           *redis.Client
	social        socialState
	anvilURL      string // ANVIL_API_BASE_URL (http://insight-anvil:8081)
	clickhouseURL string // CLICKHOUSE_HEALTH_URL (http://clickhouse:8123/ping); empty = not configured
	socialHTTP    string // SOCIAL_HTTP_BASE_URL — internal social HTTP port (CONSOLE-SOCIAL-A1)
	version       string
	httpc         *http.Client

	// CONSOLE-SOCIAL-B enforcement plane (wired via WithEnforcement; nil ⇒ 503).
	mod           moderationPort
	revoker       sessionRevoker
	setAgentState agentStateSetter
}

func NewHandlers(db *pgxpool.Pool, rdb *redis.Client, social socialState, anvilURL, clickhouseURL, socialHTTP, version string) *Handlers {
	return &Handlers{
		db: db, rdb: rdb, social: social,
		anvilURL: strings.TrimRight(anvilURL, "/"), clickhouseURL: clickhouseURL,
		socialHTTP: strings.TrimRight(socialHTTP, "/"),
		version:    version, httpc: &http.Client{Timeout: 4 * time.Second},
	}
}

// ---- operator session guard (mirrors operator.requireSession) ----

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

// requireOperator returns the operator role if the bearer maps to a live,
// non-revoked, unexpired operator session; otherwise writes 401 and false.
func (h *Handlers) requireOperator(w http.ResponseWriter, r *http.Request) (string, bool) {
	tok := bearer(r)
	if tok == "" {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "missing_operator_session"})
		return "", false
	}
	var role string
	err := h.db.QueryRow(r.Context(), `
SELECT o.role
  FROM operator_sessions s
  JOIN operators o ON o.id = s.operator_id
 WHERE s.token_hash = $1 AND s.revoked_at IS NULL AND s.expires_at > now() AND o.is_active = TRUE
 LIMIT 1`, tokenHash(tok)).Scan(&role)
	if err != nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "invalid_operator_session"})
		return "", false
	}
	return role, true
}

// ---- Stage 1: platform health ----

type serviceHealth struct {
	Name          string `json:"name"`
	Kind          string `json:"kind"`   // service | datastore
	Status        string `json:"status"` // up | degraded | down
	LastCheckedAt string `json:"last_checked_at"`
	LatencyMs     int64  `json:"latency_ms"`
	Error         string `json:"error,omitempty"`
	Version       string `json:"version,omitempty"`
}

func (h *Handlers) PlatformHealth(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireOperator(w, r); !ok {
		return
	}
	ctx := r.Context()
	out := []serviceHealth{
		{Name: "insight-gateway", Kind: "service", Status: "up", LastCheckedAt: now(), LatencyMs: 0, Version: h.version},
		h.socialHealth(),
		h.httpHealth(ctx, "insight-anvil", "service", h.anvilURL+"/health"),
		h.pgHealth(ctx),
		h.redisHealth(ctx),
		h.clickhouseHealth(ctx),
	}
	writeJSON(w, http.StatusOK, map[string]any{"services": out, "checked_at": now()})
}

func (h *Handlers) socialHealth() serviceHealth {
	s := serviceHealth{Name: "insight-social", Kind: "service", LastCheckedAt: now()}
	if h.social == nil {
		s.Status, s.Error = "down", "social client not dialed"
		return s
	}
	switch h.social.State() {
	case connectivity.Ready, connectivity.Idle:
		s.Status = "up"
	case connectivity.Connecting:
		s.Status, s.Error = "degraded", "connecting"
	default:
		s.Status, s.Error = "down", "grpc unreachable"
	}
	return s
}

func (h *Handlers) pgHealth(ctx context.Context) serviceHealth {
	s := serviceHealth{Name: "postgres", Kind: "datastore", LastCheckedAt: now()}
	t := time.Now()
	c, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	if err := h.db.Ping(c); err != nil {
		s.Status, s.Error = "down", err.Error()
	} else {
		s.Status = "up"
	}
	s.LatencyMs = time.Since(t).Milliseconds()
	return s
}

func (h *Handlers) redisHealth(ctx context.Context) serviceHealth {
	s := serviceHealth{Name: "redis", Kind: "datastore", LastCheckedAt: now()}
	t := time.Now()
	c, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	if h.rdb == nil {
		s.Status, s.Error = "down", "redis client not configured"
		return s
	}
	if err := h.rdb.Ping(c).Err(); err != nil {
		s.Status, s.Error = "down", err.Error()
	} else {
		s.Status = "up"
	}
	s.LatencyMs = time.Since(t).Milliseconds()
	return s
}

func (h *Handlers) clickhouseHealth(ctx context.Context) serviceHealth {
	if h.clickhouseURL == "" {
		return serviceHealth{Name: "clickhouse", Kind: "datastore", Status: "down",
			LastCheckedAt: now(), Error: "CLICKHOUSE_HEALTH_URL not configured"}
	}
	return h.httpHealth(ctx, "clickhouse", "datastore", h.clickhouseURL)
}

func (h *Handlers) httpHealth(ctx context.Context, name, kind, url string) serviceHealth {
	s := serviceHealth{Name: name, Kind: kind, LastCheckedAt: now()}
	if url == "" || strings.HasPrefix(url, "/health") {
		s.Status, s.Error = "down", "endpoint not configured"
		return s
	}
	t := time.Now()
	c, cancel := context.WithTimeout(ctx, 4*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(c, http.MethodGet, url, nil)
	resp, err := h.httpc.Do(req)
	s.LatencyMs = time.Since(t).Milliseconds()
	if err != nil {
		s.Status, s.Error = "down", err.Error()
		return s
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 500 {
		s.Status, s.Error = "down", "status "+resp.Status
	} else if resp.StatusCode >= 400 {
		s.Status, s.Error = "degraded", "status "+resp.Status
	} else {
		s.Status = "up"
	}
	return s
}

// ---- Stage 7: audit (operator_audit_log) ----

func (h *Handlers) Audit(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireOperator(w, r); !ok {
		return
	}
	limit := clampLimit(r.URL.Query().Get("limit"), 100, 500)
	rows, err := h.db.Query(r.Context(), `
SELECT a.id, a.event_type, a.operator_id, COALESCE(o.username, ''), a.request_id, a.metadata, a.created_at
  FROM operator_audit_log a
  LEFT JOIN operators o ON o.id = a.operator_id
 ORDER BY a.created_at DESC
 LIMIT $1`, limit)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"items": []any{}, "total": 0, "unavailable": true, "detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, action, actor, username string
		var requestID *string
		var meta map[string]any
		var createdAt time.Time
		if err := rows.Scan(&id, &action, &actor, &username, &requestID, &meta, &createdAt); err != nil {
			continue
		}
		sev := "info"
		if strings.Contains(action, "failed") {
			sev = "warning"
		}
		items = append(items, map[string]any{
			"id": id, "action": action, "actor_id": actor, "actor_display_name": username,
			"service": "gateway", "severity": sev, "request_id": deref(requestID),
			"metadata": meta, "created_at": createdAt.UTC().Format(time.RFC3339),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": len(items)})
}

// ---- Stage 8/9: admin users / operators / sessions (read-only) ----

func (h *Handlers) AdminUsers(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireOperator(w, r); !ok {
		return
	}
	limit := clampLimit(r.URL.Query().Get("limit"), 100, 500)
	rows, err := h.db.Query(r.Context(), `
SELECT id, username, user_id, created_at, last_login_at
  FROM auth_credentials ORDER BY created_at DESC LIMIT $1`, limit)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"users": []any{}, "unavailable": true, "detail": err.Error()})
		return
	}
	defer rows.Close()
	users := []map[string]any{}
	for rows.Next() {
		var id, username, userID string
		var createdAt time.Time
		var lastLogin *time.Time
		if err := rows.Scan(&id, &username, &userID, &createdAt, &lastLogin); err != nil {
			continue
		}
		users = append(users, map[string]any{
			"id": id, "username": username, "user_id": userID,
			"created_at":    createdAt.UTC().Format(time.RFC3339),
			"last_login_at": tstr(lastLogin),
			// phone/avatar live in social/identity, joined client-side when available.
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"users": users, "total": len(users)})
}

func (h *Handlers) AdminOperators(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireOperator(w, r); !ok {
		return
	}
	rows, err := h.db.Query(r.Context(), `
SELECT id, username, email, role, is_active, created_at,
       (SELECT max(last_seen_at) FROM operator_sessions s WHERE s.operator_id = o.id) AS last_seen
  FROM operators o ORDER BY created_at ASC`)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"operators": []any{}, "unavailable": true, "detail": err.Error()})
		return
	}
	defer rows.Close()
	ops := []map[string]any{}
	for rows.Next() {
		var id, username, email, role string
		var active bool
		var createdAt time.Time
		var lastSeen *time.Time
		if err := rows.Scan(&id, &username, &email, &role, &active, &createdAt, &lastSeen); err != nil {
			continue
		}
		ops = append(ops, map[string]any{
			"id": id, "username": username, "email": email,
			"role": NormalizeRole(role), "permissions": PermissionsForRole(NormalizeRole(role)),
			"is_active": active, "created_at": createdAt.UTC().Format(time.RFC3339),
			"last_login_at": tstr(lastSeen),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"operators": ops, "total": len(ops)})
}

func (h *Handlers) AdminSessions(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireOperator(w, r); !ok {
		return
	}
	var userActive, userRevoked, opActive, opRevoked int
	_ = h.db.QueryRow(r.Context(), `SELECT
   count(*) FILTER (WHERE revoked_at IS NULL AND expires_at > now()),
   count(*) FILTER (WHERE revoked_at IS NOT NULL) FROM auth_refresh_sessions`).Scan(&userActive, &userRevoked)
	_ = h.db.QueryRow(r.Context(), `SELECT
   count(*) FILTER (WHERE revoked_at IS NULL AND expires_at > now()),
   count(*) FILTER (WHERE revoked_at IS NOT NULL) FROM operator_sessions`).Scan(&opActive, &opRevoked)
	writeJSON(w, http.StatusOK, map[string]any{
		"user_sessions":     map[string]int{"active": userActive, "revoked": userRevoked},
		"operator_sessions": map[string]int{"active": opActive, "revoked": opRevoked},
		"checked_at":        now(),
	})
}

// ---- helpers ----

func now() string { return time.Now().UTC().Format(time.RFC3339) }
func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
func tstr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339)
}
func clampLimit(raw string, def, max int) int {
	if raw == "" {
		return def
	}
	n := 0
	for _, c := range raw {
		if c < '0' || c > '9' {
			return def
		}
		n = n*10 + int(c-'0')
	}
	if n <= 0 {
		return def
	}
	if n > max {
		return max
	}
	return n
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if status != http.StatusNoContent {
		_ = json.NewEncoder(w).Encode(v)
	}
}
