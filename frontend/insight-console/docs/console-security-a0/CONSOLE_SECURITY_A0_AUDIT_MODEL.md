# CONSOLE-SECURITY-A0 — Canonical Administrative Audit Model

`lib/control-plane/security/audit/model.ts`. Distinct from application logs, Control Plane
observability, IOC operational events, domain events, and Operation-lifecycle events.

## Event shape (`AdministrativeAuditEvent`)
```
eventId, occurredAt, correlationId, requestId
actor:        { operatorId, identityId, sessionId, roles, authStrength }
delegation:   { active, subjectType, subjectId, mode, reason, grantId }
action:       { capability, domain, resource, action }
target:       { environmentId, serviceId, resourceType, resourceId }
authorization:{ decision, reasonCode, policySource }
outcome:      { status, errorCode, retryable }
context:      { reason, metadata }
```
Answers WHO / WHAT / WHERE / WHICH RESOURCE / WHICH CAPABILITY / WHICH AUTHORIZATION / OUTCOME /
WHY / CORRELATION. It is a **superset of the Gateway `operator_audit_log`** (id/action/actor_id/
actor_display_name/target/service/request_id/correlation_id/metadata/created_at) so the two
federate by `correlationId` (one canonical spine — ADR-0005).

## Lifecycle statuses
`REQUESTED · AUTHORIZED · DENIED · STARTED · COMPLETED · FAILED · CANCELLED`. Not every action emits
every state; the meaningful ones are the decision (AUTHORIZED/DENIED) and the outcome
(COMPLETED/FAILED/CANCELLED).

## Safe metadata rules (`safeMetadata`)
- Scalar values only (`string | number | boolean | null`). Objects/arrays/functions are **dropped**
  — request bodies are never dumped.
- Keys matching `token|secret|password|cookie|authorization|credential|bearer|x-internal` are
  **dropped**.
- Strings truncated to 512 chars.
- No tokens, no passwords, no internal service credentials, no internal URLs. (Tested: an event
  built with `{token:"SECRET", body:{…}}` serializes without `SECRET` and without the object.)

The core carries **no domain-specific fields** — reusable by moderation, publication, identity
delegation, agent admin, the future Operation Service and Executor.
