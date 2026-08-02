# CONSOLE-SECURITY-A1 — Audit Ingest Contract

`POST /v1/console/audit/events` (gateway; `console/audit_ingest.go`). Constrained: the caller
supplies CONTEXT; the Gateway derives IDENTITY and generates CANONICAL fields. It is NOT a generic
"accept arbitrary audit JSON" endpoint.

## Trust model (both required)
1. **Trusted service authentication** — `X-Console-Service-Token` (enforced by `consolemw` at the
   route; constant-time compare vs `CONSOLE_SERVICE_TOKEN`; empty ⇒ 503 fail-closed). Only the
   Console server holds it.
2. **Verified human operator** — `Authorization: Bearer <operator session>`; the handler resolves
   the operator id + role from `operator_sessions` server-side. This is the operator identity used —
   never a body value.

## Field ownership
| Caller-supplied | Gateway-derived / validated | Server-generated |
|-----------------|-----------------------------|------------------|
| correlation_id, request_id | operator_id (from session) | event_id (`gen_random_uuid()`) |
| capability (`domain.resource.action`) | session_id (`sha256(token)`) | created_at / occurred_at (`now()`) |
| status (lifecycle) | operator role / session validity | persistence status |
| target {environment_id, service_id, resource_type, resource_id} | caller authorization (consolemw) | canonical row identity |
| authorization {decision, reason_code, policy_source} | | |
| reason, metadata (sanitized) | | |
| idempotency_key | | |

**Rejected/ignored:** any body `operator_id`, `session_id`, `event_id`, `occurred_at`/`created_at` —
never decoded, never authoritative (LIVE-PROVEN: a body `operator_id:"SPOOFED-ATTACKER"` persisted as
the real admin id).

## Validation (fail-closed)
- capability: `^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$`, ≤128 chars.
- status ∈ {REQUESTED, AUTHORIZED, DENIED, STARTED, COMPLETED, FAILED, CANCELLED}.
- authorization.decision ∈ {allow, deny}.
- idempotency_key: required, ≤200 chars.
- body ≤ 16 KiB (`MaxBytesReader` → 413).
- metadata: scalar values only; keys matching `token|secret|password|cookie|authorization|
  credential|bearer|x-internal` dropped; strings ≤512; objects/arrays dropped (no body dumping).

## Response (no DB internals, no stack traces)
`201 { event_id, persisted:true, duplicate, correlation_id, occurred_at }`. Errors: 400 (validation),
401 (missing/invalid session or service token), 413 (oversize), 500 (`audit_persist_error`, generic).

## Why this design (trust decision)
Reused the existing `consolemw` service-token mechanism (no new weak static header) + the existing
operator-session validation (no auth redesign). The Gateway remains authoritative for durable
persistence; the Console is a trusted-but-constrained caller.
