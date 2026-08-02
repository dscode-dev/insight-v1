# CONSOLE-SECURITY-A1 — Stage 0: Re-audit of the Real Audit Chain

**Date:** 2026-07-03. Grounds the sprint in the real gateway + console code (authoritative over
docs). No code-vs-doc conflicts found; SECURITY-A0 state confirmed.

## Console (writer/reader) — post SECURITY-A0
- OperatorContext + resolver + AdministrativeRequestContext: present, server-derived.
- `AdministrativeAuditWriter` (`audit/writer.ts`) → `getAuditRepository()` → **InMemory** when
  unconfigured (non-durable) → `reconciliationNeeded`. ← the PARTIAL blocker.
- Audit read `/api/v1/audit/events(/:id)` → `getAuditRepository().query()`.
- Real mutation paths: moderation (server-derived `moderator_id`), data-intelligence proxy
  (`X-Operator` server-derived), control operations (`/tmp`). Explorer `X-Operator` = the SECURITY-A0
  debt. Atlas via `X-Internal-Token` (service identity).

## Gateway (canonical spine) — real code
- **`operator_audit_log`** (migration 00006): `id, operator_id, event_type, request_id, metadata
  jsonb, created_at` — **minimal**; no first-class capability/correlation/authz/outcome/idempotency.
- Write path today: `operator/handlers.go` `INSERT INTO operator_audit_log (operator_id, event_type,
  metadata)` — operator auth events.
- Read path: `console/handlers.go` `Audit` (`GET /v1/console/audit`), operator-session gated.
- **Moderation audit** persists to its OWN `moderation_actions` table (`application/moderation/
  service.go`) — a domain audit, distinct from `operator_audit_log`.
- Session validation: `operator_sessions` (`token_hash = sha256(token)`, `revoked_at`, `expires_at`,
  `is_active`). `requireOperator` returns **role only** (extended this sprint to also yield the id).
- Service-to-service auth: `consolemw.Require(CONSOLE_SERVICE_TOKEN)` (constant-time; **503 when the
  token is empty** — fail-closed). Wraps moderation mutations.
- Build/deploy: Go 1.26 (local), goose migrations bundled in the image (`gateway-migrate` one-shot),
  build context `modules_v1/`. Cloud compose at `/home/darlansimplicio/Insight/`.

## Trust boundaries (confirmed)
- `/v1/console/*` reads: operator Bearer (server-validated). `/v1/admin/moderation/*` mutations:
  `consolemw` service token. Two distinct authenticators.

## Remaining privileged direct clients (SECURITY-A0 inventory, revalidated)
- `lib/data-intelligence.ts` `explorerCall` (`X-Operator`), `atlasIntelligenceCall`
  (`X-Internal-Token`). `lib/cloud.ts`. `lib/operations-domain.ts` (`/tmp`).

## Compatibility differences (Console canonical event ↔ Gateway schema)
The Console `AdministrativeAuditEvent` is a superset; `operator_audit_log` lacks capability/
correlation/authz/outcome/idempotency columns → **additive migration 00007** (Stage 3). Existing
rows/reads remain compatible (new columns nullable).

**Finding (surfaced live during deploy):** `CONSOLE_SERVICE_TOKEN` was **unset** in the cloud
gateway env — so the entire `consolemw` admin surface (moderation **and** the new ingest) was
fail-closed 503. Activating it (Stage 17) also restored the moderation mutation path.
