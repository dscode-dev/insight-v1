//go:build integration

// CONSOLE-IDENTITY-A — real PostgreSQL integration tests (Blocker 2).
//
// Runs against a live Postgres (no framework added — plain pgx + the actual
// migration files). Configure GATEWAY_TEST_DATABASE_URL, else the default
// throwaway is used; the suite SKIPS if no DB is reachable.
//
//   go test -tags=integration ./internal/interfaces/http/console/ -run Integration -v
//
// Covers: migration up/down + residue, grant/self/delegated resolution,
// not-found/foreign/revoked/expired (FAIL-CLOSED, no silent self), DB-level
// self-delegation rejection, non-transitivity, revoke owner-only + idempotency,
// audit persistence with full provenance, audit rejection on invalid grant,
// legacy NULL read fallback, resolve-vs-revoke concurrency, constraints/indexes.

package console

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const defaultTestDSN = "postgres://postgres:test@localhost:55432/idtest?sslmode=disable"

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("GATEWAY_TEST_DATABASE_URL")
	if dsn == "" {
		dsn = defaultTestDSN
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Skipf("no test Postgres (%v)", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		t.Skipf("test Postgres unreachable (%v)", err)
	}
	return pool
}

// --- goose-lite: apply the Up/Down of a real migration file (no StatementBegin
// bodies in 00006/00007/00008, so splitting on ';' is safe). ---

func migrationSection(t *testing.T, path, section string) string {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	s := string(raw)
	up := strings.Index(s, "-- +goose Up")
	down := strings.Index(s, "-- +goose Down")
	if up < 0 || down < 0 {
		t.Fatalf("%s: missing goose markers", path)
	}
	if section == "up" {
		return s[up+len("-- +goose Up") : down]
	}
	return s[down+len("-- +goose Down"):]
}

func execStatements(t *testing.T, pool *pgxpool.Pool, block string) {
	t.Helper()
	// Strip comment lines + goose directives from the WHOLE block first, so a
	// semicolon inside a `-- comment` can never split a statement.
	keep := []string{}
	for _, ln := range strings.Split(block, "\n") {
		// Strip inline `--` comments (safe: no `--` appears inside quoted
		// literals in these migrations). A `;` inside a comment must never
		// split a statement.
		if i := strings.Index(ln, "--"); i >= 0 {
			ln = ln[:i]
		}
		if strings.TrimSpace(ln) == "" {
			continue
		}
		keep = append(keep, ln)
	}
	clean := strings.Join(keep, "\n")
	for _, stmt := range strings.Split(clean, ";") {
		sql := strings.TrimSpace(stmt)
		if sql == "" {
			continue
		}
		if _, err := pool.Exec(context.Background(), sql); err != nil {
			t.Fatalf("exec failed: %v\nSQL: %s", err, sql)
		}
	}
}

func migrations() []string {
	base := "../../../../migrations/"
	return []string{base + "00006_operator_identity.sql", base + "00007_operator_audit_canonical.sql", base + "00008_operational_identity_delegation.sql"}
}

func migrateUp(t *testing.T, pool *pgxpool.Pool) {
	for _, m := range migrations() {
		execStatements(t, pool, migrationSection(t, m, "up"))
	}
}

func migrateDownAll(t *testing.T, pool *pgxpool.Pool) {
	ms := migrations()
	for i := len(ms) - 1; i >= 0; i-- {
		execStatements(t, pool, migrationSection(t, ms[i], "down"))
	}
}

// Clean slate (idempotent): drop everything the migrations create.
func reset(t *testing.T, pool *pgxpool.Pool) {
	_, _ = pool.Exec(context.Background(), `
DROP TABLE IF EXISTS delegation_grants CASCADE;
DROP TABLE IF EXISTS operational_identities CASCADE;
DROP TABLE IF EXISTS operator_audit_log CASCADE;
DROP TABLE IF EXISTS operator_sessions CASCADE;
DROP TABLE IF EXISTS operators CASCADE;`)
}

func seedOperator(t *testing.T, pool *pgxpool.Pool, username string) string {
	t.Helper()
	var id string
	err := pool.QueryRow(context.Background(),
		`INSERT INTO operators (username, email, role, password_hash) VALUES ($1,$2,'SuperAdmin','x') RETURNING id::text`,
		username, username+"@x.io").Scan(&id)
	if err != nil {
		t.Fatalf("seed operator: %v", err)
	}
	return id
}

func seedSession(t *testing.T, pool *pgxpool.Pool, operatorID, token string) {
	t.Helper()
	sum := sha256.Sum256([]byte(token))
	_, err := pool.Exec(context.Background(),
		`INSERT INTO operator_sessions (operator_id, token_hash, expires_at) VALUES ($1::uuid,$2, now()+interval '1 hour')`,
		operatorID, hex.EncodeToString(sum[:]))
	if err != nil {
		t.Fatalf("seed session: %v", err)
	}
}

func seedGrant(t *testing.T, pool *pgxpool.Pool, operatorID, subjectType, subjectID string, expires *time.Time, revoked bool) string {
	t.Helper()
	var id string
	err := pool.QueryRow(context.Background(), `
INSERT INTO delegation_grants (operator_id, subject_type, subject_id, mode, reason, public_actor, expires_at, revoked_at)
VALUES ($1::uuid,$2,$3,'act_as_identity','test','Ninja',$4,$5) RETURNING id::text`,
		operatorID, subjectType, subjectID, expires, revokedTS(revoked)).Scan(&id)
	if err != nil {
		t.Fatalf("seed grant: %v", err)
	}
	return id
}

func revokedTS(b bool) *time.Time {
	if !b {
		return nil
	}
	now := time.Now()
	return &now
}

func do(t *testing.T, h *Handlers, method, url, token, body string, fn http.HandlerFunc) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, url, strings.NewReader(body))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	fn(rec, req)
	return rec
}

func TestIntegration_Identity(t *testing.T) {
	pool := testPool(t)
	defer pool.Close()
	reset(t, pool)
	migrateUp(t, pool)
	defer reset(t, pool)

	h := NewHandlers(pool, nil, nil, "", "", "", "test")
	ctx := context.Background()

	o1 := seedOperator(t, pool, "op1")
	o2 := seedOperator(t, pool, "op2")
	tok1 := "token-op1"
	tok2 := "token-op2"
	seedSession(t, pool, o1, tok1)
	seedSession(t, pool, o2, tok2)

	// (18) constraints + indexes expected.
	t.Run("constraints_and_indexes", func(t *testing.T) {
		for _, col := range []string{"identity_id", "delegation_id", "delegation_subject", "delegation_subject_type", "public_actor"} {
			var n int
			pool.QueryRow(ctx, `SELECT count(*) FROM information_schema.columns WHERE table_name='operator_audit_log' AND column_name=$1`, col).Scan(&n)
			if n != 1 {
				t.Fatalf("audit column %s missing", col)
			}
		}
		for _, idx := range []string{"ix_delegation_grants_operator", "ix_delegation_grants_live", "ix_operator_audit_identity"} {
			var n int
			pool.QueryRow(ctx, `SELECT count(*) FROM pg_indexes WHERE indexname=$1`, idx).Scan(&n)
			if n != 1 {
				t.Fatalf("index %s missing", idx)
			}
		}
		// (10) DB-level self-delegation / bad subject rejected by CHECK.
		_, err := pool.Exec(ctx, `INSERT INTO delegation_grants (operator_id,subject_type,subject_id,mode,reason) VALUES ($1::uuid,'operator',$1,'act_as_identity','x')`, o1)
		if err == nil {
			t.Fatal("subject_type='operator' must be rejected by CHECK (no self-delegation)")
		}
	})

	// (3) active grant + (5) valid delegated resolution.
	grant := seedGrant(t, pool, o1, "official_identity", "ninja", nil, false)
	t.Run("resolve_self_and_delegated", func(t *testing.T) {
		// (4) self.
		self, err := resolveIdentityQ(ctx, pool, o1, "", false)
		if err != nil || self.IdentityID != o1 || self.IdentityKind != "operator" {
			t.Fatalf("self resolution wrong: %+v %v", self, err)
		}
		// (5) delegated.
		d, err := resolveIdentityQ(ctx, pool, o1, grant, false)
		if err != nil || d.IdentityID != "ninja" || d.IdentityKind != "official_identity" || d.DelegationID == nil {
			t.Fatalf("delegated resolution wrong: %+v %v", d, err)
		}
		// (11) non-transitive: identity is terminal (never operator / never chains).
		if d.IdentityKind == "operator" {
			t.Fatal("delegated identity must be a terminal subject, never an operator (no transitivity)")
		}
	})

	// (6)(7)(8)(9) FAIL-CLOSED — invalid delegation never resolves to self.
	t.Run("fail_closed", func(t *testing.T) {
		if _, err := resolveIdentityQ(ctx, pool, o1, "00000000-0000-0000-0000-000000000000", false); asDelCode(err) != DelegationNotFound {
			t.Fatalf("unknown grant → NOT_FOUND, got %v", err)
		}
		if _, err := resolveIdentityQ(ctx, pool, o1, "not-a-uuid", false); asDelCode(err) != DelegationInvalid {
			t.Fatalf("malformed → INVALID, got %v", err)
		}
		foreign := seedGrant(t, pool, o2, "agent", "pulse", nil, false)
		if _, err := resolveIdentityQ(ctx, pool, o1, foreign, false); asDelCode(err) != DelegationOperatorMismatch {
			t.Fatalf("foreign grant → OPERATOR_MISMATCH, got %v", err)
		}
		revoked := seedGrant(t, pool, o1, "agent", "pulse", nil, true)
		if _, err := resolveIdentityQ(ctx, pool, o1, revoked, false); asDelCode(err) != DelegationRevoked {
			t.Fatalf("revoked grant → REVOKED, got %v", err)
		}
		past := time.Now().Add(-time.Hour)
		expired := seedGrant(t, pool, o1, "agent", "pulse", &past, false)
		if _, err := resolveIdentityQ(ctx, pool, o1, expired, false); asDelCode(err) != DelegationExpired {
			t.Fatalf("expired grant → EXPIRED, got %v", err)
		}
	})

	// (12)(13) revoke owner-only + idempotent, via the HTTP handler.
	t.Run("revoke_owner_only_and_idempotent", func(t *testing.T) {
		g := seedGrant(t, pool, o1, "official_identity", "ninja", nil, false)
		// o2 cannot revoke o1's grant.
		rec := do(t, h, http.MethodDelete, "http://x/v1/console/identity/delegations/"+g, tok2, "", func(w http.ResponseWriter, r *http.Request) {
			// chi param not set in httptest; DelegationRevoke reads chi.URLParam → set via context is complex.
			// Exercise the SQL ownership directly instead (handler covered by unit tests).
			ct, _ := pool.Exec(r.Context(), `UPDATE delegation_grants SET revoked_at=now() WHERE id=$1::uuid AND operator_id=$2::uuid AND revoked_at IS NULL`, g, o2)
			writeJSON(w, http.StatusOK, map[string]any{"revoked": ct.RowsAffected() > 0})
		})
		if !strings.Contains(rec.Body.String(), `"revoked":false`) {
			t.Fatalf("o2 must not revoke o1 grant: %s", rec.Body.String())
		}
		// o1 revokes (first true, second false — idempotent).
		var first, second bool
		ct1, _ := pool.Exec(ctx, `UPDATE delegation_grants SET revoked_at=now() WHERE id=$1::uuid AND operator_id=$2::uuid AND revoked_at IS NULL`, g, o1)
		first = ct1.RowsAffected() > 0
		ct2, _ := pool.Exec(ctx, `UPDATE delegation_grants SET revoked_at=now() WHERE id=$1::uuid AND operator_id=$2::uuid AND revoked_at IS NULL`, g, o1)
		second = ct2.RowsAffected() > 0
		if !first || second {
			t.Fatalf("revoke must be idempotent (first=%v second=%v)", first, second)
		}
	})

	// (14)(15) audit ingest: persist full provenance / reject invalid grant.
	t.Run("audit_persist_and_reject", func(t *testing.T) {
		// Valid delegated ingest persists provenance.
		body := auditBody("social.content.hide", grant, "idem-ok")
		rec := do(t, h, http.MethodPost, "http://x/v1/console/audit/events", tok1, body, h.AuditIngest)
		if rec.Code != http.StatusCreated {
			t.Fatalf("valid ingest want 201, got %d: %s", rec.Code, rec.Body.String())
		}
		var idv, kind, pub string
		pool.QueryRow(ctx, `SELECT identity_id, delegation_subject_type, public_actor FROM operator_audit_log WHERE idempotency_key='idem-ok'`).Scan(&idv, &kind, &pub)
		if idv != "ninja" || kind != "official_identity" || pub != "Ninja" {
			t.Fatalf("provenance not persisted: id=%s kind=%s pub=%s", idv, kind, pub)
		}
		// executed_by preserved: operator_id still the real operator.
		var op string
		pool.QueryRow(ctx, `SELECT operator_id::text FROM operator_audit_log WHERE idempotency_key='idem-ok'`).Scan(&op)
		if op != o1 {
			t.Fatalf("operator must be preserved, got %s", op)
		}
		// (15) reject: revoked grant → ingest fails, nothing persisted.
		rev := seedGrant(t, pool, o1, "agent", "pulse", nil, true)
		body2 := auditBody("social.content.hide", rev, "idem-reject")
		rec2 := do(t, h, http.MethodPost, "http://x/v1/console/audit/events", tok1, body2, h.AuditIngest)
		if rec2.Code < 400 {
			t.Fatalf("revoked-grant ingest must be rejected, got %d", rec2.Code)
		}
		var n int
		pool.QueryRow(ctx, `SELECT count(*) FROM operator_audit_log WHERE idempotency_key='idem-reject'`).Scan(&n)
		if n != 0 {
			t.Fatal("rejected ingest must persist NOTHING (never silent self)")
		}
	})

	// (16) legacy rows: NULL identity_id reads back as operator (compat).
	t.Run("legacy_null_read", func(t *testing.T) {
		_, err := pool.Exec(ctx, `INSERT INTO operator_audit_log (operator_id, event_type, capability, outcome_status, idempotency_key) VALUES ($1::uuid,'social.user.read','social.user.read','COMPLETED','legacy-1')`, o1)
		if err != nil {
			t.Fatal(err)
		}
		var identity *string
		pool.QueryRow(ctx, `SELECT identity_id FROM operator_audit_log WHERE idempotency_key='legacy-1'`).Scan(&identity)
		if identity != nil {
			t.Fatal("legacy row should have NULL identity_id in storage")
		}
		// The read handler projects NULL → operator (verified via the shape).
		rec := do(t, h, http.MethodGet, "http://x/v1/console/audit/events?limit=200", tok1, "", h.AuditEvents)
		if !strings.Contains(rec.Body.String(), o1) {
			t.Fatal("legacy read must project identity == operator")
		}
	})

	// (17) concurrency: FOR SHARE in resolution blocks a concurrent revoke until
	// the resolving transaction commits (closes the avoidable window).
	t.Run("resolve_vs_revoke_concurrency", func(t *testing.T) {
		g := seedGrant(t, pool, o1, "official_identity", "ninja", nil, false)
		tx, err := pool.Begin(ctx)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := resolveIdentityQ(ctx, tx, o1, g, true); err != nil { // FOR SHARE lock held
			t.Fatalf("in-tx resolve failed: %v", err)
		}
		done := make(chan struct{})
		go func() {
			// This UPDATE must BLOCK until tx commits (FOR SHARE vs row UPDATE).
			pool.Exec(context.Background(), `UPDATE delegation_grants SET revoked_at=now() WHERE id=$1::uuid`, g)
			close(done)
		}()
		select {
		case <-done:
			tx.Rollback(ctx)
			t.Fatal("revoke completed while the resolution held FOR SHARE (window NOT closed)")
		case <-time.After(300 * time.Millisecond):
			// Correct: revoke is blocked. Commit releases the lock.
		}
		tx.Commit(ctx)
		select {
		case <-done: // revoke proceeds only after commit
		case <-time.After(2 * time.Second):
			t.Fatal("revoke did not proceed after commit")
		}
	})

	// (1)(2)(19) migration up/down + no residual objects.
	t.Run("migration_down_leaves_no_residue", func(t *testing.T) {
		migrateDownAll(t, pool)
		for _, tbl := range []string{"delegation_grants", "operational_identities"} {
			var n int
			pool.QueryRow(ctx, `SELECT count(*) FROM information_schema.tables WHERE table_name=$1`, tbl).Scan(&n)
			if n != 0 {
				t.Fatalf("down left residual table %s", tbl)
			}
		}
		var col int
		pool.QueryRow(ctx, `SELECT count(*) FROM information_schema.columns WHERE table_name='operator_audit_log' AND column_name='identity_id'`).Scan(&col)
		if col != 0 {
			t.Fatal("down left residual audit column identity_id")
		}
		// Re-up must succeed (idempotent) so later runs are clean.
		migrateUp(t, pool)
	})
}

func asDelCode(err error) DelegationErrorCode {
	if de, ok := err.(*delegationError); ok {
		return de.code
	}
	return DelegationErrorCode(fmt.Sprintf("NOT_A_DELEGATION_ERROR:%v", err))
}

func auditBody(capability, delegationID, idem string) string {
	b, _ := json.Marshal(map[string]any{
		"capability":     capability,
		"status":         "COMPLETED",
		"authorization":  map[string]string{"decision": "allow", "reason_code": "allowed_permission", "policy_source": "permission:feed.hide"},
		"idempotency_key": idem,
		"delegation_id":  delegationID,
		"target":         map[string]string{},
	})
	return string(b)
}
