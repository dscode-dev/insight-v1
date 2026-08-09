// CONSOLE-IDENTITY-A — Operational Identity + Delegation (Gateway is the AUTHORITY).
//
// The Gateway owns the delegation grant store and identity resolution. The Console
// never forges identity: it can only reference a grant by id; the Gateway validates
// that grant belongs to the verified operator and is live, then DERIVES the
// effective identity / subject / public actor server-side.
//
// Invariants enforced here:
//   * The authenticated operator is ALWAYS preserved (executed_by = operator).
//   * Delegation is explicit, revocable, non-transitive (subject is terminal).
//   * Default path: no delegation → identity_id == operator_id (backward compatible).
//   * No impersonation / acting-as / session switching. A grant only makes an
//     operator ABLE to author as a subject on an explicit, audited action.

package console

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

// resolvedIdentity is the server-derived authoring context for one operator +
// optional delegation reference. Operator is never dropped.
type resolvedIdentity struct {
	OperatorID          string
	IdentityID          string  // effective operational identity (== operator when no delegation)
	IdentityKind        string  // operator | official_identity | agent
	DelegationID        *string // nil when acting as self
	DelegationSubject   *string
	DelegationSubjectTy *string
	PublicActor         *string
}

// DelegationErrorCode is a stable, non-sensitive reason for a delegation that
// cannot be used ACTIVELY. FAIL-CLOSED: when a delegation_id is explicitly
// supplied it MUST resolve to a valid grant or FAIL — never a silent fallback
// to self. (Absent delegation_id resolves to self; that is not an error.)
type DelegationErrorCode string

const (
	DelegationNotFound         DelegationErrorCode = "DELEGATION_NOT_FOUND"
	DelegationRevoked          DelegationErrorCode = "DELEGATION_REVOKED"
	DelegationExpired          DelegationErrorCode = "DELEGATION_EXPIRED"
	DelegationOperatorMismatch DelegationErrorCode = "DELEGATION_OPERATOR_MISMATCH"
	DelegationInvalid          DelegationErrorCode = "DELEGATION_INVALID"
)

type delegationError struct{ code DelegationErrorCode }

func (e *delegationError) Error() string { return string(e.code) }

func delErr(c DelegationErrorCode) *delegationError { return &delegationError{code: c} }

// rowQuerier is satisfied by BOTH *pgxpool.Pool and pgx.Tx, so resolution can run
// read-only (GET) or inside a locking transaction (audit ingest).
type rowQuerier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// resolveIdentity is THE authoritative resolution (read-only). See resolveIdentityQ.
func (h *Handlers) resolveIdentity(ctx context.Context, operatorID, delegationID string) (resolvedIdentity, error) {
	return resolveIdentityQ(ctx, h.db, operatorID, delegationID, false)
}

// resolveIdentityQ resolves the effective identity FAIL-CLOSED. `forShare` takes a
// row-level share lock on the grant so a concurrent revoke cannot slip in between
// resolution and a same-transaction persistence (closes the avoidable window).
//
//	delegationID == ""        → self (identity == operator).
//	delegationID valid+live   → delegated identity.
//	delegationID invalid      → *delegationError (NEVER self).
//
// Invalid = malformed / not found / foreign operator / revoked / expired /
// incompatible subject / any state that does not allow active use.
func resolveIdentityQ(ctx context.Context, q rowQuerier, operatorID, delegationID string, forShare bool) (resolvedIdentity, error) {
	if delegationID == "" {
		return resolvedIdentity{OperatorID: operatorID, IdentityID: operatorID, IdentityKind: "operator"}, nil
	}
	sql := `
SELECT operator_id::text, subject_type, subject_id, mode, public_actor, revoked_at, expires_at
  FROM delegation_grants
 WHERE id = $1::uuid`
	if forShare {
		sql += " FOR SHARE"
	}
	var (
		grantOperator, subjectType, subjectID, mode string
		publicActor                                 *string
		revokedAt, expiresAt                        *time.Time
	)
	err := q.QueryRow(ctx, sql, delegationID).Scan(
		&grantOperator, &subjectType, &subjectID, &mode, &publicActor, &revokedAt, &expiresAt)
	if err != nil {
		// Malformed uuid ⇒ invalid_text_representation (22P02): treat as INVALID.
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "22P02" {
			return resolvedIdentity{}, delErr(DelegationInvalid)
		}
		if errors.Is(err, pgx.ErrNoRows) {
			return resolvedIdentity{}, delErr(DelegationNotFound)
		}
		return resolvedIdentity{}, err // real infra error (not a delegation error)
	}
	// Ownership: never usable by another operator (enumeration-safe at HTTP layer).
	if grantOperator != operatorID {
		return resolvedIdentity{}, delErr(DelegationOperatorMismatch)
	}
	if revokedAt != nil {
		return resolvedIdentity{}, delErr(DelegationRevoked)
	}
	if expiresAt != nil && !expiresAt.After(time.Now()) {
		return resolvedIdentity{}, delErr(DelegationExpired)
	}
	if subjectType != "official_identity" && subjectType != "agent" {
		return resolvedIdentity{}, delErr(DelegationInvalid)
	}
	did := delegationID
	return resolvedIdentity{
		OperatorID:          operatorID,
		IdentityID:          subjectID, // effective authoring identity is the subject
		IdentityKind:        subjectType,
		DelegationID:        &did,
		DelegationSubject:   &subjectID,
		DelegationSubjectTy: &subjectType,
		PublicActor:         publicActor,
	}, nil
}

// writeDelegationError maps a delegation error to HTTP, preserving the padrão de
// erros existente. Enumeration-safe: NOT_FOUND and OPERATOR_MISMATCH share an
// INDISTINGUISHABLE public response (404 "delegation_not_usable"); the real
// reason is kept in the server log only. The operator's OWN grant states
// (revoked/expired/invalid) are specific.
func writeDelegationError(w http.ResponseWriter, operatorID string, de *delegationError) {
	switch de.code {
	case DelegationRevoked:
		writeJSON(w, http.StatusConflict, map[string]string{"detail": "delegation_revoked"})
	case DelegationExpired:
		writeJSON(w, http.StatusConflict, map[string]string{"detail": "delegation_expired"})
	case DelegationInvalid:
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "delegation_invalid"})
	case DelegationNotFound, DelegationOperatorMismatch:
		// Indistinguishable externally — never reveal another operator's grants.
		slog.Warn("delegation_not_usable", "operator_id", operatorID, "reason", string(de.code))
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "delegation_not_usable"})
	default:
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "delegation_invalid"})
	}
}

// IdentityResolve — GET /v1/console/identity/resolve[?delegation_id=...].
// Returns the effective authoring identity for the verified operator. The browser
// cannot set operator/identity/actor; only the delegation_id reference is read.
func (h *Handlers) IdentityResolve(w http.ResponseWriter, r *http.Request) {
	operatorID, _, _, ok := h.requireOperatorFull(w, r)
	if !ok {
		return
	}
	ri, err := h.resolveIdentity(r.Context(), operatorID, r.URL.Query().Get("delegation_id"))
	if err != nil {
		var de *delegationError
		if errors.As(err, &de) {
			// FAIL-CLOSED: an explicitly requested delegation that is not usable
			// is an error, never a silent self fallback.
			writeDelegationError(w, operatorID, de)
			return
		}
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "identity_resolve_error"})
		return
	}
	writeJSON(w, http.StatusOK, identityJSON(ri))
}

func identityJSON(ri resolvedIdentity) map[string]any {
	var delegation any = nil
	if ri.DelegationID != nil {
		delegation = map[string]any{
			"delegation_id": *ri.DelegationID,
			"subject_type":  deref(ri.DelegationSubjectTy),
			"subject_id":    deref(ri.DelegationSubject),
		}
	}
	return map[string]any{
		// executed_by ALWAYS present — the real operator, never dropped.
		"executed_by":   "operator:" + ri.OperatorID,
		"operator_id":   ri.OperatorID,
		"identity_id":   ri.IdentityID,
		"identity_kind": ri.IdentityKind,
		"public_actor":  derefPtr(ri.PublicActor),
		"delegation":    delegation,
	}
}

// DelegationGrant — POST /v1/console/identity/delegations. Creates an explicit,
// revocable grant for the verified operator. subject_type/subject_id/mode/reason
// required. Operator is the session operator (never the body).
func (h *Handlers) DelegationGrant(w http.ResponseWriter, r *http.Request) {
	operatorID, _, _, ok := h.requireOperatorFull(w, r)
	if !ok {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 8*1024)
	var body struct {
		SubjectType string   `json:"subject_type"`
		SubjectID   string   `json:"subject_id"`
		Mode        string   `json:"mode"`
		Scope       []string `json:"scope"`
		Reason      string   `json:"reason"`
		PublicActor string   `json:"public_actor"`
		ExpiresAt   string   `json:"expires_at"`
		// operator_id / identity_id are NEVER read from the body.
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_json"})
		return
	}
	if body.SubjectType != "official_identity" && body.SubjectType != "agent" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_subject_type"})
		return
	}
	if body.Mode != "act_as_identity" && body.Mode != "act_through_agent" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_mode"})
		return
	}
	if body.SubjectID == "" || body.Reason == "" || len(body.Reason) > 512 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "subject_and_reason_required"})
		return
	}
	var expiresAt any
	if body.ExpiresAt != "" {
		t, err := time.Parse(time.RFC3339, body.ExpiresAt)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_expires_at"})
			return
		}
		expiresAt = t
	}
	var pub any
	if body.PublicActor != "" {
		pub = clip(body.PublicActor, 200)
	}
	if body.Scope == nil {
		body.Scope = []string{}
	}
	var id string
	var issuedAt time.Time
	err := h.db.QueryRow(r.Context(), `
INSERT INTO delegation_grants (operator_id, subject_type, subject_id, mode, scope, reason, public_actor, expires_at)
VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)
RETURNING id::text, issued_at`,
		operatorID, body.SubjectType, clip(body.SubjectID, 200), body.Mode, body.Scope,
		clip(body.Reason, 512), pub, expiresAt).Scan(&id, &issuedAt)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "grant_persist_error"})
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"delegation_id": id, "operator_id": operatorID, "subject_type": body.SubjectType,
		"subject_id": body.SubjectID, "mode": body.Mode, "issued_at": issuedAt.UTC().Format(time.RFC3339Nano),
	})
}

// DelegationRevoke — DELETE /v1/console/identity/delegations/{id}. Idempotent;
// an operator can only revoke their OWN grant.
func (h *Handlers) DelegationRevoke(w http.ResponseWriter, r *http.Request) {
	operatorID, _, _, ok := h.requireOperatorFull(w, r)
	if !ok {
		return
	}
	id := chi.URLParam(r, "id")
	if id == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "missing_id"})
		return
	}
	ct, err := h.db.Exec(r.Context(), `
UPDATE delegation_grants SET revoked_at = now()
 WHERE id = $1::uuid AND operator_id = $2::uuid AND revoked_at IS NULL`, id, operatorID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "revoke_error"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"delegation_id": id, "revoked": ct.RowsAffected() > 0})
}

// DelegationList — GET /v1/console/identity/delegations. The verified operator's
// own grants (never another operator's).
func (h *Handlers) DelegationList(w http.ResponseWriter, r *http.Request) {
	operatorID, _, _, ok := h.requireOperatorFull(w, r)
	if !ok {
		return
	}
	rows, err := h.db.Query(r.Context(), `
SELECT id::text, subject_type, subject_id, mode, reason, public_actor, issued_at, expires_at, revoked_at
  FROM delegation_grants WHERE operator_id = $1::uuid
 ORDER BY issued_at DESC LIMIT 200`, operatorID)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"items": []any{}, "unavailable": true})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, subjectType, subjectID, mode, reason string
		var publicActor *string
		var issuedAt time.Time
		var expiresAt, revokedAt *time.Time
		if err := rows.Scan(&id, &subjectType, &subjectID, &mode, &reason, &publicActor, &issuedAt, &expiresAt, &revokedAt); err != nil {
			continue
		}
		active := revokedAt == nil && (expiresAt == nil || expiresAt.After(time.Now()))
		items = append(items, map[string]any{
			"delegation_id": id, "subject_type": subjectType, "subject_id": subjectID, "mode": mode,
			"reason": reason, "public_actor": derefPtr(publicActor), "active": active,
			"issued_at":  issuedAt.UTC().Format(time.RFC3339Nano),
			"expires_at": tsPtr(expiresAt), "revoked_at": tsPtr(revokedAt),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "count": len(items)})
}

func derefPtr(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}
func tsPtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.UTC().Format(time.RFC3339Nano)
}
