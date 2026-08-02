# CONSOLE-SECURITY-A0 — Migration & Legacy Containment

## Stage 11 — Moderation (flagship, migrated)
`app/api/v1/moderation/actions/route.ts`:
- Identity now the canonical `OperatorContext` (`resolveOperatorContext`).
- `assertNoClientActor(body)` strips any client `moderator_id` (observability logs the attempt).
- **Authorization via the seam:** `authorize(operator, "social.content.moderate",
  ACTION_PERMISSION[action], target)`.
- **Canonical audit:** `AUTHORIZED|DENIED` before the call, `COMPLETED|FAILED` after.
- **Compatibility bridge:** upstream `moderator_id` populated from the trusted context
  (`operatorUsername ?? operatorId`) — never from the browser.
- Behavior unchanged; no new capability; Social rules untouched. Also durably audited Gateway-side
  (operator_audit_log).

## Stage 12 — Nexus publication (N/A — documented)
`app/api/v1/publications/**` and `/nexus/**` are **empty scaffold directories** (no route.ts). There
is no real publication mutation path to migrate. When implemented, it MUST consume this foundation
(OperatorContext + authorize + AdministrativeAudit). No code added (no fake path).

## Stage 13 — Control Panel operations (attribution migrated; domain NOT redesigned)
`app/api/v1/control/operations/route.ts`:
- Lifecycle attribution bound to `OperatorContext` (`operatorContextFromOperator`, no extra Gateway call).
- Canonical audit emitted on create/approve/cancel (`platform.operation.<intent>`, status
  COMPLETED/CANCELLED).
- The ephemeral `/tmp` Operation domain is **untouched** (CONSOLE-OPERATIONS-A); `execution_enabled`
  stays `false`; no executor activated.

## Stage 14 — Legacy direct privileged client containment
| Path | Classification | Action |
|------|----------------|--------|
| `lib/data-intelligence.ts` `explorerCall` (`X-Operator`) | KEEP_TEMPORARILY | already server-derived from the session operator; contain + wrap behind an adapter in a later sprint |
| `lib/data-intelligence.ts` `atlasIntelligenceCall` (`X-Internal-Token`) | WRAP_BEHIND_ADAPTER | service credential, server-only; not a human identity; migrate behind the boundary (ADR-0003) |
| `lib/cloud.ts` (Atlas/Explorer direct) | KEEP_TEMPORARILY | documented remaining direct path; internal token server-only |
| `lib/operations-domain.ts` (`/tmp`) | KEEP_TEMPORARILY | attribution migrated; durable store = CONSOLE-OPERATIONS-A |

**Remaining self-asserted attribution as AUTHORITATIVE: none.** All actor values are server-derived.
`X-Operator` remains as a server-derived string to Explorer (contained, documented), not a browser
value.

## What SOCIAL-A inherits
`resolveOperatorContext` · `authorize` · `AdministrativeAudit` (decision/outcome) ·
`assertNoClientActor` · delegation-preserving audit · the audit read surface. New Social admin
routes consume these directly — no new identity/audit mechanism to invent.
