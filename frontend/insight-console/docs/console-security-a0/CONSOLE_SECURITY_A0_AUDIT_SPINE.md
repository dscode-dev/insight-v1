# CONSOLE-SECURITY-A0 — Audit Spine Decision, Persistence & Consistency

## Evidence-based spine decision → **EXTEND_EXISTING_SPINE**
- A canonical, durable audit spine ALREADY exists and is **Gateway-owned**: `operator_audit_log`
  in cloud Postgres `insight_auth` (CONFIRMED live: table exists). Moderation actions already flow
  into it Gateway-side.
- The Console can currently **READ** it (`GET /v1/console/audit` → live 401, exists+gated) but
  **cannot WRITE** to it — the Gateway exposes no Console audit-ingest endpoint.
- The Console owns no database (its `lib/db.ts` is a deprecated no-op; it is a stateless BFF).

**Decision:** the canonical spine is `operator_audit_log`; the target is to EXTEND it with a
Gateway audit-ingest endpoint the Console writes to. Until that ships, the Console persists its own
canonical events in a **durable, superset-compatible Postgres store** (`control_plane_audit_event`,
migration `db/migrations/0001_control_plane_audit.sql`), config-gated by `CONSOLE_AUDIT_DATABASE_URL`,
federating by `correlationId`. We do **not** create a competing schema — it mirrors the Gateway's.

## Persistence
- `PostgresAuditRepository` — durable, keyset pagination, parameterized filters, idempotent append
  (`ON CONFLICT (event_id) DO NOTHING`). Activated by `CONSOLE_AUDIT_DATABASE_URL`.
- `InMemoryAuditRepository` — dev/tests only, `durable:false`.
- **NEVER** `/tmp`, JSON files, or browser storage.
- **Honest activation gap:** in the current deploy neither `CONSOLE_AUDIT_DATABASE_URL` is set nor
  the migration applied, so the runtime repository is in-memory (`durable:false`). The writer +
  observability surface this via `reconciliationNeeded:true` and `audit_reconciliation_needed` —
  **a log is never called canonical audit.** This is the reason the sprint verdict is PARTIAL.

## Consistency model (honest — no invented atomicity)
| Case | Behavior |
|------|----------|
| A. Authorization fails | Emit `DENIED` audit; return 403; **no mutation** |
| B. Upstream mutation fails | Emit `FAILED` audit (errorCode/retryable); propagate the error |
| C. Audit-intent write fails **before** mutation | Not swallowed: `audit_write_failed` + `reconciliationNeeded`; the flagship path (moderation) still has Gateway-side durable audit |
| D. Audit-outcome write fails **after** mutation | Not swallowed: `reconciliationNeeded` marker for later reconciliation |
| E. Response delivery fails after success | Mutation + audit already recorded; correlationId enables reconciliation |
| F. Duplicate/retry | Idempotent append on `event_id` (Postgres); no exactly-once claim across services |

We do **not** claim distributed atomicity. The model is: **audit intent (AUTHORIZED/DENIED) before
mutation, correlated outcome (COMPLETED/FAILED) after**, with an explicit reconciliation state when
persistence is unavailable/non-durable.
