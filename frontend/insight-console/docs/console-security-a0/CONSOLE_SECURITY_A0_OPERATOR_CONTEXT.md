# CONSOLE-SECURITY-A0 — Operator & Request Context

## OperatorContext (`lib/control-plane/security/operator-context.ts`)
Canonical, server-owned, immutable (`Object.freeze`) administrative identity. Built ONLY from a
server-verified operator; the browser can never override it.

| Field | Provenance |
|-------|-----------|
| `operatorId` | Gateway session (`operator.id`) — always present |
| `operatorDisplayName` / `operatorUsername` | Gateway session (username used only for upstream bridges) |
| `identityId` | == `operatorId` today (operator == identity; split in CONSOLE-IDENTITY-A) |
| `sessionId` | **`sha256(token)`** — the REAL Gateway session key; non-secret; distinct from correlation/request |
| `roles` / `permissions` | Gateway-issued |
| `authStrength` | `null` (ABSENT in contract — not fabricated) |
| `authenticatedAt` | `null` (ABSENT — not fabricated) |
| `delegation` | `null` (no active delegation this sprint) |
| `correlationId` / `requestId` | request headers (distinct concepts) |
| `source` | `"insight-console"` |

**Resolvers:**
- `resolveOperatorContext(req)` — verifies the session via Gateway `/me`; throws 401 if
  missing/invalid. The single canonical resolver (routes never interpret claims independently).
- `operatorContextFromOperator(operator, req)` — build from an already-verified operator (avoids a
  second Gateway round-trip) for routes that already called `requireOperator()`.
- `buildOperatorContext(operator, token, req)` — pure, testable core.
- `assertNoClientActor(body)` — strips `operator_id/moderator_id/actor_id/act_as_user_id/…` so a
  client value can never become authoritative (observability records the attempt).

## AdministrativeRequestContext (`request-context.ts`)
Wraps the trusted `OperatorContext` + safe correlation metadata, keeping the **five identifiers
distinct** (never collapsed):

| Identifier | Meaning |
|-----------|---------|
| `requestId` | one HTTP request |
| `correlationId` | links a distributed administrative action chain |
| `sessionId` | the authenticated session (`sha256(token)`, in `actor`) |
| `operationId` | the future durable Operation domain (NOT set here) |
| `auditEventId` | one audit record (assigned by the writer) |

A random request UUID is never used as a session id; a correlation id never replaces attribution.
