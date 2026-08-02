package console

import (
	"net/http/httptest"
	"strings"
	"testing"
)

// CONSOLE-IDENTITY-A — provenance projection is pure + testable without a DB.
// The SQL resolution (resolveIdentity/grant/revoke) requires Postgres and is
// exercised in integration; here we prove the invariant shape: executed_by is
// ALWAYS present and the operator is never dropped, delegated or not.

func TestIdentityJSON_SelfIsBackwardCompatible(t *testing.T) {
	ri := resolvedIdentity{OperatorID: "op-1", IdentityID: "op-1", IdentityKind: "operator"}
	out := identityJSON(ri)
	if out["executed_by"] != "operator:op-1" {
		t.Fatalf("executed_by must always be the operator, got %v", out["executed_by"])
	}
	if out["identity_id"] != "op-1" {
		t.Fatalf("self identity must equal operator, got %v", out["identity_id"])
	}
	if out["identity_kind"] != "operator" {
		t.Fatal("self kind must be operator")
	}
	if out["delegation"] != nil {
		t.Fatal("self action must have no delegation")
	}
	if out["public_actor"] != nil {
		t.Fatal("self action must have no public actor")
	}
}

func TestIdentityJSON_DelegatedPreservesOperator(t *testing.T) {
	did, subj, ty, pub := "grant-9", "ninja", "official_identity", "Ninja"
	ri := resolvedIdentity{
		OperatorID: "op-1", IdentityID: subj, IdentityKind: ty,
		DelegationID: &did, DelegationSubject: &subj, DelegationSubjectTy: &ty, PublicActor: &pub,
	}
	out := identityJSON(ri)
	// Operator is NEVER dropped under delegation.
	if out["executed_by"] != "operator:op-1" {
		t.Fatalf("operator must be preserved, got %v", out["executed_by"])
	}
	// Identity becomes the subject.
	if out["identity_id"] != "ninja" || out["identity_kind"] != "official_identity" {
		t.Fatalf("identity must be the delegated subject, got %v/%v", out["identity_id"], out["identity_kind"])
	}
	if out["public_actor"] != "Ninja" {
		t.Fatalf("public_actor must surface, got %v", out["public_actor"])
	}
	d, ok := out["delegation"].(map[string]any)
	if !ok || d["delegation_id"] != "grant-9" || d["subject_id"] != "ninja" || d["subject_type"] != "official_identity" {
		t.Fatalf("delegation block wrong: %v", out["delegation"])
	}
}

func TestDerefTsPtr_NilSafe(t *testing.T) {
	if derefPtr(nil) != nil {
		t.Fatal("derefPtr(nil) must be nil")
	}
	s := "x"
	if derefPtr(&s) != "x" {
		t.Fatal("derefPtr must deref")
	}
	if tsPtr(nil) != nil {
		t.Fatal("tsPtr(nil) must be nil")
	}
}

// CONSOLE-IDENTITY-A closeout — enumeration-safe, fail-closed error mapping (pure).
func TestWriteDelegationError_EnumerationSafeMapping(t *testing.T) {
	cases := []struct {
		code   DelegationErrorCode
		status int
		detail string
	}{
		{DelegationRevoked, 409, "delegation_revoked"},
		{DelegationExpired, 409, "delegation_expired"},
		{DelegationInvalid, 400, "delegation_invalid"},
		{DelegationNotFound, 404, "delegation_not_usable"},
		{DelegationOperatorMismatch, 404, "delegation_not_usable"},
	}
	for _, c := range cases {
		rec := httptest.NewRecorder()
		writeDelegationError(rec, "op-1", &delegationError{code: c.code})
		if rec.Code != c.status {
			t.Fatalf("%s: status %d want %d", c.code, rec.Code, c.status)
		}
		if !strings.Contains(rec.Body.String(), c.detail) {
			t.Fatalf("%s: body %q want %q", c.code, rec.Body.String(), c.detail)
		}
	}
	a, b := httptest.NewRecorder(), httptest.NewRecorder()
	writeDelegationError(a, "op-1", &delegationError{code: DelegationNotFound})
	writeDelegationError(b, "op-1", &delegationError{code: DelegationOperatorMismatch})
	if a.Body.String() != b.Body.String() || a.Code != b.Code {
		t.Fatal("NOT_FOUND and OPERATOR_MISMATCH must be externally indistinguishable")
	}
}
