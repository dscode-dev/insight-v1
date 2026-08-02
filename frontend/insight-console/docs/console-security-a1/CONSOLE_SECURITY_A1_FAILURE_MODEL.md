# CONSOLE-SECURITY-A1 — Failure Model

The durable primary path is `AdministrativeAuditWriter → GatewayAuditRepository → Gateway ingest →
operator_audit_log`. There is **no silent in-memory production fallback**: memory is used ONLY with
`CONSOLE_AUDIT_MODE=memory` (dev/tests). Absent that, the factory returns the durable Gateway
repository.

## Writer behavior
`AdministrativeAudit.record()` calls `repo.append()`. The `GatewayAuditRepository`:
- bounded timeout (4s), one retry on transport/5xx (same idempotency key ⇒ no dup),
- on 201/200 ⇒ `audit_write_succeeded`,
- on non-persist ⇒ **throws** ⇒ the writer returns `AuditWriteResult{persisted:false,
  reconciliationNeeded:true}` + emits `audit_write_failed`/`audit_reconciliation_needed`. Never
  swallowed.

## Per-route matrix
| Case | Behavior |
|------|----------|
| Authorization DENIED | emit DENIED audit; 403; no mutation |
| **High-risk mutation (moderation), AUTHORIZED intent NOT durably persisted** | **FAIL-CLOSED: 503 `audit_unavailable`; the mutation does NOT run** (`moderation/actions` checks `intent.persisted`) |
| Upstream mutation fails | emit FAILED audit (errorCode/retryable); propagate error |
| Lower-risk / preview (Control Panel, execution_enabled=false) | proceed with reconciliation marker if audit non-durable; never fabricate success |
| Audit-outcome write fails after a successful distributed action | `reconciliationNeeded` marker; correlationId enables later reconciliation |
| Duplicate/retry | idempotent (idempotency_key) — no double row |

## Guarantees / non-guarantees
- Consistency model: **audit intent (AUTHORIZED/DENIED) before mutation, correlated outcome
  (COMPLETED/FAILED) after.** High-risk mutations are gated on durable intent.
- **No distributed atomicity or exactly-once is claimed.** The honest guarantee is at-least-once
  delivery + idempotent persistence, with fail-closed on the high-risk intent.
