# CONSOLE-SECURITY-A1 — Final Report

**Date:** 2026-07-03 · **Classification: `READY`**

## 1. Final classification — READY
Production Console audit writes now durably reach the canonical Gateway spine
(`operator_audit_log`). Ingestion is authenticated (service token) + operator-verified; attribution
is gateway-derived and un-overridable; retries are idempotent; read-back is proven against the real
DB; the Control Panel uses the durable path; moderation audit is intact and its admin surface was
(re)activated; Explorer privileged attribution is behind a typed operator-bound adapter; and there is
no silent in-memory production fallback. Live-validated on both environments.

## 2. Executive result
The SECURITY-A0 PARTIAL blocker — "the canonical audit model exists but the Console does not write
durably to the platform spine" — is CLOSED. The Console (Robozão) writes canonical events through a
typed Gateway audit adapter to the Cloud Gateway ingest endpoint, which derives the operator from the
verified session and persists to `operator_audit_log`.

## 3. Previous PARTIAL blocker
Console-originated audit persisted to an in-memory store (`reconciliationNeeded`); no Gateway ingest
existed; the Console could read but not write the spine.

## 4. Baseline audit topology
`operator_audit_log` (minimal: id/operator_id/event_type/request_id/metadata/created_at), operator
session validation (`operator_sessions`), `consolemw` service-token gate, moderation domain audit in
`moderation_actions`. (See BASELINE.)

## 5. Chosen trust model
Service authentication (`X-Console-Service-Token`/`consolemw`) **+** verified operator session
(Bearer → `operator_sessions`). A service token alone does not prove a human; the operator is
gateway-derived, never body-supplied.

## 6. Audit ingest contract
`POST /v1/console/audit/events` — constrained: caller supplies context (correlation/capability/target/
status/authz/metadata/idempotency_key); Gateway derives operator/session/timestamps/event_id;
validated + sanitized + size-bounded + idempotent. Read: `GET /v1/console/audit/events` (canonical).

## 7. Authentication model
Opaque operator session, server-validated (`token_hash=sha256`, revoked/expiry/active). No auth
redesign.

## 8. Authorization model
`consolemw` service gate + operator session; the Console-side capability seam (SECURITY-A0) governs
the action decision. Capability presence never authorizes.

## 9. Operator verification chain
Browser → Console BFF → `resolveOperatorContext` → Gateway `/me` (verified) → ingest with Bearer →
Gateway re-resolves operator id from `operator_sessions` → persisted operator = verified operator.
**Live proof:** body `operator_id:"SPOOFED-ATTACKER"` persisted as the real admin id `6261b0cb…`.

## 10. Schema mapping
Additive migration 00007 adds first-class canonical columns + idempotency unique index; superset of
`operator_audit_log`; 52 prior rows preserved. (See SCHEMA_MAPPING.)

## 11. Idempotency semantics
`idempotency_key` (per submission; ≠ event/request/correlation/operation id) + partial-unique index +
`ON CONFLICT DO NOTHING`. Live: repeat key → `duplicate:true`, same event_id, `count=1`.

## 12. Delivery guarantee
**At-least-once delivery + idempotent persistence.** No exactly-once, no distributed atomicity.

## 13. Failure model
Fail-closed for high-risk mutations (moderation aborts 503 if AUTHORIZED intent not durable); FAILED
audit on upstream error; reconciliation marker otherwise; never silent. No silent memory fallback
(memory only via `CONSOLE_AUDIT_MODE=memory`).

## 14. Reconciliation model
Correlation-chain terminal-state detection + `reconciliationNeeded` signal + idempotent replay; no
workflow engine. (See RECONCILIATION.)

## 15. Control Panel migration
`control/operations` binds attribution to OperatorContext and emits canonical audit
(`platform.operation.*`) through the durable writer; `/tmp` domain untouched; `execution_enabled=false`.

## 16. Moderation convergence
Moderation keeps `moderation_actions` (domain) + emits canonical `operator_audit_log` via ingest when
Console-driven. One canonical spine; no rerouting of gateway-internal moderation through HTTP. The
`consolemw` surface (moderation + ingest) was **activated** (CONSOLE_SERVICE_TOKEN was unset → 503).

## 17. Explorer privileged adapter closure
`explorer-privileged.ts`: `X-Operator` server-derived from OperatorContext, browser cannot set it,
correlation propagated. Honest: Explorer does not verify `X-Operator` (attribution, not auth) — future
debt recorded, flow contained.

## 18. Remaining privileged direct clients
Atlas `X-Internal-Token` (frozen, read-only, service identity) KEEP; `lib/cloud.ts`,
`operations-domain.ts` KEEP_TEMPORARILY; Nexus scaffolds NOT_IMPLEMENTED. No authoritative
client-asserted actor remains.

## 19. Test results
Gateway: `go build`/`go vet`/`go test ./...` **all pass** (incl. new `audit_ingest_test.go`: capability/
status/sanitize/clip). Console: `tsc`/`lint`/`check:boundaries`/`build` clean, `vitest` **69 pass**
(+7: durable factory, gateway-sink mapping, Explorer adapter), `git diff --check` clean.

## 20. Migration validation
Applied live via `gateway-migrate` (goose → version 7); additive; 52 existing rows preserved; columns
+ idempotency index verified against the real `insight_auth` DB.

## 21. Image tags & digests
- `konohalabs/insight-gateway:0.1.10` — `sha256:5976eed048402800eb310a48f18c05e855575086057f31d8d859740c8a11e421` (rollback: 0.1.9 `4b1a5e8e5392`).
- `konohalabs/insight-console:0.3.19` — `sha256:fc679ce0de5f1a3b016d418861a26c4c470c679a7afcd229fd818483c5f8e335` (rollback: 0.3.18).

## 22. Google Cloud deployment evidence
Gateway 0.1.10 running, restarts=0, routes registered; migration version 7; CONSOLE_SERVICE_TOKEN
activated; nginx reloaded; app edge + auth/social unaffected; end-to-end ingest→DB proven.

## 23. Robozão deployment evidence
Console 0.3.19 running, health=healthy, restarts=0, "Ready"; `CONSOLE_AUDIT_MODE` unset (durable
Gateway default); `ADMIN_API_BASE_URL` = cloud gateway; service token matches. Atlas 1.0.0 untouched.

## 24. Live audit write/read-back evidence
Minted temp admin session (deleted after) → ingest (spoofed body) → `persisted:true` → DB row:
operator=real admin (not spoofed), capability/outcome/correlation preserved, `has_token=false`,
source=insight-console; idempotent repeat `count=1`. (See LIVE_VALIDATION.)

## 25. Known limitations
- Explorer does not verify `X-Operator` (contained, not auth) — future debt.
- Canonical read is offset/limit at the Gateway (cursor pagination is a future extension); the Console
  read projection defaults roles/delegation (first-class security dims are columns).
- No scheduled reconciliation sweeper (detection + idempotent replay suffice for V1).
- Gateway `settings.Version` constant still reports 0.1.8 (cosmetic; image is 0.1.10).

## 26. SECURITY-A0 promotion decision
**SECURITY-A0 is promoted PARTIAL → READY.** Its sole open blocker (durable canonical audit) is closed
and live-proven.

## 27. Readiness for CONSOLE-SOCIAL-A
Ready. Social **read** admin builds on OperatorContext + authorize + the now-durable
AdministrativeAudit + canonical read — no new identity/audit mechanism.

## 28. Remaining prerequisites for CONSOLE-SOCIAL-B (mutations)
None blocking on audit/identity. Recommended before broad Social mutation: (a) per-action Social admin
capabilities + dual-control for destructive actions; (b) optional Explorer-side operator verification;
(c) cursor pagination on the canonical read. The trusted identity + durable audit foundation is
complete.

---
**Verdict:** the trusted administrative identity + durable canonical audit chain is complete and
live-proven end-to-end across both environments. A durable table the Console can actually write to,
with authenticated ingest, gateway-derived attribution, idempotent persistence, and DB read-back —
not a log line, not a 200 without read-back, not a service token masquerading as a human.
