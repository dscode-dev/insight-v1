# CONSOLE-SECURITY-A1 — Live Dual-Environment Validation

Controlled, read-mostly. The one write is a self-test audit event (`platform.audit.selftest`) — no
Social mutation, no ban, no content removal, no Atlas/Explorer intelligence change, no executor. A
temporary operator session was minted for the real `admin` operator and **deleted** afterward
(reversible fixture).

## Gateway routes live (public edge, after nginx reload)
`/healthz` 200 · `/v1/operator/auth/me` 401 · `/v1/console/audit` 401 · **`GET /v1/console/audit/events`
401** · **`POST /v1/console/audit/events` 401** (after token activation; was 503) · app edge
`/v1/feed/global` 401 (unaffected). Direct-to-gateway (bypass nginx) confirmed all routes served.

## End-to-end canonical audit (the durable-spine proof)
Minted admin session → `/v1/operator/auth/me` → role **SuperAdmin** (real `operator_sessions` path).
`POST /v1/console/audit/events` with a **spoofed** body `operator_id:"SPOOFED-ATTACKER"` +
`session_id:"SPOOFED"` + `metadata.token:"MUST_NOT_PERSIST"`:

| Check | Evidence |
|-------|----------|
| Persisted | `persisted:true`, `event_id 777c9a4b-…` |
| **Operator NOT overridable** | DB row `operator_id = 6261b0cb-… (real admin)`, **not** SPOOFED |
| Session server-derived | `session_id` = `sha256(token)` (not the body value) |
| Capability/outcome/correlation | `capability=platform.audit.selftest`, `out=COMPLETED`, `corr=corr-a1-live` |
| **No secret persisted** | `metadata ? 'token'` = **false** (sanitized) |
| Source | `source=insight-console` |
| **Idempotency** | repeat same key → `duplicate:true`, same `event_id`; `count(*) = 1` |
| Read-back | row present in `operator_audit_log` (canonical spine) |
| Timestamp server-controlled | `occurred_at`/`created_at` set by gateway `now()` |

## Trust checks
- Unauthorized ingest rejected: no service token → 503/401; no operator session → 401.
- Browser actor override has no effect (proven above).
- A service token alone does not prove a human operator (both required).

## Platform integrity
- Gateway healthy, restarts=0; existing auth/social/moderation routes unaffected (401s as before);
  52 prior audit rows preserved.
- Atlas 1.0.0 unchanged; no Explorer intelligence mutation; no Social content mutation; no executor;
  `execution_enabled=false`.
- Robozão: Console authenticates against Cloud identity (unchanged); Console 0.3.19 deployed for the
  durable production writer.

**No production evidence was fabricated.** The temporary admin session was deleted (`DELETE 1`).
