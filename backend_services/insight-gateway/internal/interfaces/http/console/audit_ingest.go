// CONSOLE-SECURITY-A1 — canonical administrative audit ingestion + read.
//
// Trust model: the caller must present BOTH the Console service token (enforced by
// consolemw at the route) AND a valid operator session Bearer. The human operator
// identity is DERIVED SERVER-SIDE from the verified session — the request body can
// never set operator_id, session_id, event_id, or created_at. Persistence is
// idempotent (partial-unique idempotency_key). This is the durable extension of the
// canonical spine (operator_audit_log).

package console

import (
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

const maxAuditBody = 16 * 1024 // 16 KiB

var capabilityRe = regexp.MustCompile(`^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$`)

var auditStatuses = map[string]bool{
	"REQUESTED": true, "AUTHORIZED": true, "DENIED": true, "STARTED": true,
	"COMPLETED": true, "FAILED": true, "CANCELLED": true,
}

var forbiddenMetaKey = regexp.MustCompile(`(?i)token|secret|password|cookie|authorization|credential|bearer|x-internal`)

// requireOperatorFull resolves the VERIFIED operator id + role + session key from
// the Bearer session. Identity is never taken from the request body.
func (h *Handlers) requireOperatorFull(w http.ResponseWriter, r *http.Request) (operatorID, role, sessionKey string, ok bool) {
	tok := bearer(r)
	if tok == "" {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "missing_operator_session"})
		return "", "", "", false
	}
	sk := tokenHash(tok)
	if err := h.db.QueryRow(r.Context(), `
SELECT o.id::text, o.role
  FROM operator_sessions s
  JOIN operators o ON o.id = s.operator_id
 WHERE s.token_hash = $1 AND s.revoked_at IS NULL AND s.expires_at > now() AND o.is_active = TRUE
 LIMIT 1`, sk).Scan(&operatorID, &role); err != nil {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": "invalid_operator_session"})
		return "", "", "", false
	}
	return operatorID, role, sk, true
}

type auditTarget struct {
	EnvironmentID string `json:"environment_id"`
	ServiceID     string `json:"service_id"`
	ResourceType  string `json:"resource_type"`
	ResourceID    string `json:"resource_id"`
}

type auditIngestBody struct {
	CorrelationID string      `json:"correlation_id"`
	RequestID     string      `json:"request_id"`
	Capability    string      `json:"capability"`
	Status        string      `json:"status"`
	Target        auditTarget `json:"target"`
	Authorization struct {
		Decision     string `json:"decision"`
		ReasonCode   string `json:"reason_code"`
		PolicySource string `json:"policy_source"`
	} `json:"authorization"`
	Reason         string         `json:"reason"`
	Metadata       map[string]any `json:"metadata"`
	IdempotencyKey string         `json:"idempotency_key"`
	// CONSOLE-IDENTITY-A — the caller may REFERENCE a delegation grant by id. The
	// identity / subject / public_actor are NEVER trusted from the body; the
	// Gateway derives them from the authoritative grant store (resolveIdentity).
	DelegationID string `json:"delegation_id"`
	// Deliberately NOT decoded (server-controlled): operator_id, identity_id,
	// session_id, event_id, occurred_at, created_at, public_actor, delegation_subject.
}

func clip(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}

// sanitizeMeta drops forbidden keys + non-scalar values; bounds count and size.
func sanitizeMeta(in map[string]any) map[string]any {
	out := map[string]any{}
	i := 0
	for k, v := range in {
		if i >= 50 {
			break
		}
		if forbiddenMetaKey.MatchString(k) {
			continue
		}
		switch val := v.(type) {
		case string:
			out[k] = clip(val, 512)
		case float64, bool, nil:
			out[k] = val
		default:
			// objects/arrays dropped — never dump request bodies
		}
		i++
	}
	return out
}

// AuditIngest persists one canonical administrative audit event (POST
// /v1/console/audit/events). Service-token gated by consolemw at the route.
func (h *Handlers) AuditIngest(w http.ResponseWriter, r *http.Request) {
	operatorID, _, sessionKey, ok := h.requireOperatorFull(w, r)
	if !ok {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxAuditBody)
	var body auditIngestBody
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(&body); err != nil {
		if strings.Contains(err.Error(), "http: request body too large") {
			writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"detail": "audit_body_too_large"})
			return
		}
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_json"})
		return
	}

	// Validation (fail-closed).
	if !capabilityRe.MatchString(body.Capability) || len(body.Capability) > 128 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_capability"})
		return
	}
	if !auditStatuses[body.Status] {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_status"})
		return
	}
	if body.Authorization.Decision != "allow" && body.Authorization.Decision != "deny" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_authorization_decision"})
		return
	}
	if body.IdempotencyKey == "" || len(body.IdempotencyKey) > 200 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_idempotency_key"})
		return
	}

	meta := sanitizeMeta(body.Metadata)
	if body.Reason != "" {
		meta["reason"] = clip(body.Reason, 512)
	}
	metaJSON, err := json.Marshal(meta)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "audit_encode_error"})
		return
	}

	nz := func(s string, n int) any {
		s = clip(s, n)
		if s == "" {
			return nil
		}
		return s
	}
	nzp := func(p *string, n int) any {
		if p == nil {
			return nil
		}
		return clip(*p, n)
	}

	// CONSOLE-IDENTITY-A — resolution + persistence in ONE transaction. The grant
	// is share-locked (FOR SHARE) so a concurrent revoke cannot land a revoked
	// delegation into a persisted audit row (closes the avoidable window). An
	// explicitly-referenced invalid grant REJECTS the ingest — never persists as
	// self. Absent delegation_id → identity == operator (default).
	tx, err := h.db.Begin(r.Context())
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "audit_persist_error"})
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }() // no-op after commit

	ri, rerr := resolveIdentityQ(r.Context(), tx, operatorID, body.DelegationID, true)
	if rerr != nil {
		var de *delegationError
		if errors.As(rerr, &de) {
			// FAIL-CLOSED: reject; nothing is persisted (tx rolls back).
			writeDelegationError(w, operatorID, de)
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "identity_resolve_error"})
		return
	}

	var eventID string
	var createdAt time.Time
	err = tx.QueryRow(r.Context(), `
INSERT INTO operator_audit_log (
  operator_id, event_type, request_id, metadata,
  capability, correlation_id, session_id, target_environment, target_service,
  target_resource_type, target_resource_id, authz_decision, authz_reason_code,
  outcome_status, idempotency_key, source,
  identity_id, delegation_id, delegation_subject, delegation_subject_type, public_actor
) VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
  $17, $18, $19, $20, $21)
ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
RETURNING id::text, created_at`,
		operatorID, clip(body.Capability, 128), nz(body.CorrelationID, 128), string(metaJSON),
		clip(body.Capability, 128), nz(body.CorrelationID, 128), sessionKey,
		nz(body.Target.EnvironmentID, 64), nz(body.Target.ServiceID, 64),
		nz(body.Target.ResourceType, 64), nz(body.Target.ResourceID, 200),
		body.Authorization.Decision, nz(body.Authorization.ReasonCode, 64),
		body.Status, clip(body.IdempotencyKey, 200), "insight-console",
		// executed_by stays operator_id (col 1); identity_id is the effective
		// authoring identity (== operator when not delegated).
		ri.IdentityID, nzp(ri.DelegationID, 64), nzp(ri.DelegationSubject, 200),
		nzp(ri.DelegationSubjectTy, 32), nzp(ri.PublicActor, 200),
	).Scan(&eventID, &createdAt)

	duplicate := false
	if err == pgx.ErrNoRows {
		// Idempotent hit: the submission already persisted. Return the existing row.
		duplicate = true
		if e := tx.QueryRow(r.Context(),
			`SELECT id::text, created_at FROM operator_audit_log WHERE idempotency_key = $1 LIMIT 1`,
			clip(body.IdempotencyKey, 200)).Scan(&eventID, &createdAt); e != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "audit_persist_error"})
			return
		}
	} else if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "audit_persist_error"})
		return
	}
	if err := tx.Commit(r.Context()); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "audit_persist_error"})
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"event_id":       eventID,
		"persisted":      true,
		"duplicate":      duplicate,
		"correlation_id": body.CorrelationID,
		"occurred_at":    createdAt.UTC().Format(time.RFC3339Nano),
	})
}

// AuditEvents is the canonical read over operator_audit_log (GET
// /v1/console/audit/events). Operator-session gated; keyset pagination.
func (h *Handlers) AuditEvents(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireOperator(w, r); !ok {
		return
	}
	q := r.URL.Query()
	limit := clampLimit(q.Get("limit"), 50, 200)
	where := []string{"1=1"}
	args := []any{}
	add := func(col, val string) {
		if val == "" {
			return
		}
		args = append(args, val)
		where = append(where, col+" = $"+strconv.Itoa(len(args)))
	}
	add("a.correlation_id", q.Get("correlation_id"))
	add("a.operator_id::text", q.Get("operator"))
	add("a.capability", q.Get("capability"))
	add("a.target_service", q.Get("service"))
	add("a.target_environment", q.Get("environment"))
	add("a.target_resource_type", q.Get("resource_type"))
	add("a.target_resource_id", q.Get("resource_id"))
	add("a.outcome_status", q.Get("outcome"))
	if v := q.Get("since"); v != "" {
		args = append(args, v)
		where = append(where, "a.created_at >= $"+strconv.Itoa(len(args)))
	}
	if v := q.Get("until"); v != "" {
		args = append(args, v)
		where = append(where, "a.created_at <= $"+strconv.Itoa(len(args)))
	}
	args = append(args, limit)
	sql := `
SELECT a.id::text, a.event_type, a.operator_id::text, COALESCE(o.username,''), a.request_id,
       a.capability, a.correlation_id, a.session_id, a.target_environment, a.target_service,
       a.target_resource_type, a.target_resource_id, a.authz_decision, a.authz_reason_code,
       a.outcome_status, a.metadata, a.created_at,
       a.identity_id, a.delegation_id, a.delegation_subject, a.delegation_subject_type, a.public_actor
  FROM operator_audit_log a
  LEFT JOIN operators o ON o.id = a.operator_id
 WHERE ` + strings.Join(where, " AND ") + `
 ORDER BY a.created_at DESC, a.id DESC
 LIMIT $` + strconv.Itoa(len(args))
	rows, err := h.db.Query(r.Context(), sql, args...)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"items": []any{}, "unavailable": true, "detail": "audit_query_error"})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, action, operatorID, username string
		var requestID, capability, correlationID, sessionID, tEnv, tSvc, tRType, tRID, aDec, aReason, outcome *string
		var identityID, delegationID, delSubject, delSubjectType, publicActor *string
		var meta map[string]any
		var createdAt time.Time
		if err := rows.Scan(&id, &action, &operatorID, &username, &requestID, &capability, &correlationID,
			&sessionID, &tEnv, &tSvc, &tRType, &tRID, &aDec, &aReason, &outcome, &meta, &createdAt,
			&identityID, &delegationID, &delSubject, &delSubjectType, &publicActor); err != nil {
			continue
		}
		// Backward-compat: old rows have NULL identity_id → identity == operator.
		effectiveIdentity := operatorID
		if identityID != nil && *identityID != "" {
			effectiveIdentity = *identityID
		}
		var delegation any = nil
		if delegationID != nil && *delegationID != "" {
			delegation = map[string]any{
				"delegation_id": *delegationID,
				"subject_id":    deref(delSubject),
				"subject_type":  deref(delSubjectType),
			}
		}
		items = append(items, map[string]any{
			"event_id": id, "event_type": action, "operator_id": operatorID, "operator_display_name": username,
			// executed_by ALWAYS the real operator, even under delegation.
			"executed_by": "operator:" + operatorID,
			"identity_id": effectiveIdentity, "public_actor": derefPtr(publicActor), "delegation": delegation,
			"request_id": deref(requestID), "capability": deref(capability), "correlation_id": deref(correlationID),
			"session_id": deref(sessionID),
			"target": map[string]any{
				"environment_id": deref(tEnv), "service_id": deref(tSvc),
				"resource_type": deref(tRType), "resource_id": deref(tRID),
			},
			"authorization": map[string]any{"decision": deref(aDec), "reason_code": deref(aReason)},
			"outcome":       map[string]any{"status": deref(outcome)},
			"metadata":      meta, "occurred_at": createdAt.UTC().Format(time.RFC3339Nano),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "count": len(items)})
}
