# CONSOLE-SECURITY-A0 — Final Report

**Date:** 2026-07-03 · **Classification: `PARTIAL`**

## 1. Final classification — PARTIAL
The trusted **identity, attribution, authorization, and delegation** chain is READY-grade and in
use by the migrated privileged flows. The single reason the overall verdict is **PARTIAL** is
**durable canonical-audit persistence is implemented but not live-activated**: with no
`CONSOLE_AUDIT_DATABASE_URL` provisioned (and no Gateway audit-ingest endpoint yet), the runtime
audit store is in-memory and honestly flags `reconciliationNeeded`. Per this sprint's own rule, we
classify PARTIAL rather than call a non-durable store "canonical audit." (Note: the **flagship
moderation path is already durably audited Gateway-side** in `operator_audit_log`.)

## 2. Executive security result
The browser can request an administrative action but can **never declare the trusted operator**.
Identity is derived server-side from a verified, revocable Gateway session; authorization is a real
decision (not a registry lookup); every migrated mutation emits a canonical, secret-free audit
event with a preserved operator and correlation chain; delegation is shaped but inert (operator can
never be replaced).

## 3. Attribution audit summary
No Console route trusts a browser actor as authoritative (already true pre-sprint; now formalized +
guarded). `publications/nexus` routes are empty scaffolds (code-vs-audit correction). Real mutation
surfaces: moderation (migrated), control operations (attribution migrated), data-intelligence
proxy (contained), dlq replay.

## 4. Authentication trust chain
Opaque operator session issued by the Cloud Gateway; verified server-side against durable
`operator_sessions` (`insight_auth`); revocable/expiring. `sessionId = sha256(token)` is the real
session key. `authStrength`/`authenticatedAt` absent → modeled `null`.

## 5. OperatorContext architecture
Server-owned, immutable, single resolver; fields provenance-documented; `assertNoClientActor` guard;
distinct request/correlation/session ids.

## 6. Authorization architecture
`authorize()` → decision; real SuperAdmin + granular-permission rules reused; capability presence is
a precondition, never a grant; fail-closed on missing policy.

## 7. Canonical audit architecture
`AdministrativeAuditEvent` (who/what/where/resource/capability/authorization/outcome/why/correlation);
superset-compatible with `operator_audit_log`; safe-metadata sanitizer (no tokens/objects); writer
with AUTHORIZED/DENIED → COMPLETED/FAILED/CANCELLED lifecycle.

## 8. Persistence decision
**EXTEND_EXISTING_SPINE.** Canonical spine = Gateway `operator_audit_log` (durable, confirmed live).
Interim durable Console store `control_plane_audit_event` (migration provided, config-gated), never
/tmp. Activation pending (deploy step).

## 9. Audit consistency model
Audit intent before mutation, correlated outcome after; failures never swallowed
(`audit_write_failed`/`reconciliation_needed`); idempotent append on `event_id`; **no distributed
atomicity or exactly-once claimed.**

## 10. Delegation foundation
Contract present, inactive; `resolveDelegation()`→null; `rejectSelfDelegation` throws;
`assertOperatorPreserved` forbids dropping/replacing the operator. No impersonation representable.

## 11. Migrated moderation path
OperatorContext + authz seam + canonical audit + server-filled `moderator_id` bridge. Behavior
unchanged; also Gateway-durably audited.

## 12. Migrated Nexus publication path
N/A — no real route exists (empty scaffolds). Documented; must consume this foundation when built.

## 13. Control Panel attribution status
Attribution bound to OperatorContext; canonical audit on create/approve/cancel; `/tmp` domain +
`execution_enabled=false` untouched (CONSOLE-OPERATIONS-A).

## 14. Legacy attribution inventory
Authoritative client-asserted identity: **none**. Server-derived `X-Operator` string to Explorer
(contained). Static Atlas `X-Internal-Token` (service identity, server-only).

## 15. Direct privileged client inventory
`lib/data-intelligence.ts` (Explorer `X-Operator`, Atlas internal token), `lib/cloud.ts`,
`lib/operations-domain.ts` — classified KEEP_TEMPORARILY / WRAP_BEHIND_ADAPTER; internal creds
server-only.

## 16. Test results
`tsc --noEmit` ✓ · `next lint` ✓ · `check:boundaries` ✓ · `next build` ✓ (audit/events routes
compiled) · `vitest` **62/62** (5 new security suites: context/attribution, authorization, audit
model+writer+repo/pagination, delegation) · `git diff --check` clean.

## 17. Live Robozão validation
Console runs on Robozão, authenticates against Cloud identity; Atlas 1.0.0 untouched; read-only.

## 18. Live Google Cloud validation
operator-auth login 400 / me 401 / console audit 401; `operator_audit_log` + `operator_sessions`
exist (read-only). No mutations, no fabricated evidence.

## 19. Known limitations
- Durable audit **not activated** (no `CONSOLE_AUDIT_DATABASE_URL`/migration/redeploy; no Gateway
  ingest endpoint). Runtime store in-memory with honest reconciliation flags. **← the PARTIAL gap.**
- `resolveOperatorContext` verified-session path unit-tested only indirectly (needs a request scope);
  the pure builder + guards are fully tested.
- Data-intelligence `X-Operator` remains a server-derived string (contained, not yet behind an adapter).

## 20. Exact prerequisites for CONSOLE-SOCIAL-A
Ready now: `resolveOperatorContext`, `authorize`, `AdministrativeAudit`, `assertNoClientActor`,
delegation-preserving audit, audit read surface. SOCIAL-A builds Social **read** admin on these with
no new identity/audit mechanism. (Reads don't require durable audit activation.)

## 21. Exact prerequisites for CONSOLE-SOCIAL-B (mutations)
**Blocker:** activate durable canonical audit before broad Social mutations — either (a) provision
`CONSOLE_AUDIT_DATABASE_URL` + apply `0001_control_plane_audit.sql` + rebuild/redeploy console, or
(b) ship a Gateway audit-ingest endpoint (EXTEND) so Console-originated canonical events reach
`operator_audit_log`. Also recommended before B: move the Explorer `X-Operator` behind an
operator-identity-bound adapter. Moderation itself is already durably audited Gateway-side.

---
**Verdict rationale:** being strict — a non-durable runtime audit store is not canonical audit, so
the sprint is PARTIAL. Everything else (verified identity, trusted attribution, authorization seam,
canonical model, delegation preservation, migrated paths) is complete, tested, and live-validated
at the contract level. SOCIAL-A can begin immediately; SOCIAL-B waits on durable-audit activation.
