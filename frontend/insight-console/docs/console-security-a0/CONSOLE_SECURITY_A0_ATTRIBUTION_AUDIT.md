# CONSOLE-SECURITY-A0 — Stage 0: Attribution Surface Audit

Complete search of Console mutation/attribution paths. **Code-vs-audit correction:** the
CONSOLE-ARCHITECTURE-A assumption that "Publication Center is a real mutating path" is WRONG in
current code — `app/api/v1/publications/**` and `app/api/v1/nexus/**` are **empty scaffold
directories** (no `route.ts`). The real Console mutation surfaces are moderation, the
data-intelligence proxy, control operations, and dlq replay.

**Key finding (better than the audit feared):** every existing Console mutation path already
resolves the operator **server-side** via `requireOperator()`. No path treats a browser-declared
identity as authoritative today. The gap was the *absence of a canonical* OperatorContext, an
authorization *decision*, and *canonical audit* — not raw client trust.

| Occurrence | File | Action | Identity source | Mutates | Authz | Audit | Trustworthy | Classification | Recommendation |
|---|---|---|---|---|---|---|---|---|---|
| `moderator_id` | `app/api/v1/moderation/actions/route.ts:46` (pre) | moderation | `operator.username ?? id` (session) | yes | `requirePermission` | Gateway-side | yes | VERIFIED_SESSION_DERIVED | **Migrated** → OperatorContext + authz seam + canonical audit |
| `moderator_id` schema | `lib/moderation.ts` | upstream contract field | server-populated | — | — | — | yes | SERVICE_IDENTITY (bridge) | Keep as compatibility bridge (server-filled) |
| `X-Operator` | `lib/data-intelligence.ts:14,52` | Explorer proxy | `operator.username ?? displayName` (session) | yes | route perms | none | server-derived string | LEGACY_CLIENT_ASSERTED→SERVER_DERIVED | CONTAIN: server-derived, add correlation; wrap behind adapter later |
| `X-Internal-Token` | `lib/data-intelligence.ts:51`, `lib/control-plane/adapters/atlas.ts` | Atlas call | server config | (read) | n/a | none | n/a (service) | SERVICE_IDENTITY | KEEP server-only; not a human identity |
| `operator_id`/`created_by`/`approved_by` | `lib/operations-domain.ts` | operation lifecycle | `operator.*` (session), `/tmp` store | preview | internal eval | none→now audit | server-derived | VERIFIED_SESSION_DERIVED (ephemeral) | **Migrated** attribution→OperatorContext + audit; /tmp untouched (CONSOLE-OPERATIONS-A) |
| `actor_id` | `app/api/v1/audit/route.ts`, `audit/page.tsx` | audit READ | Gateway response | no | `audit.read` | read | n/a | READ | Keep |
| publications/nexus | `app/api/v1/{publications,nexus}/**` | — | — | **no route** | — | — | — | NOT_IMPLEMENTED | N/A this sprint; must consume this foundation when built |

**Classifications:** VERIFIED_SESSION_DERIVED (moderation, operations) · SERVER_DERIVED
(data-intelligence X-Operator) · SERVICE_IDENTITY (Atlas internal token) · NOT_IMPLEMENTED
(publication/nexus) · none LEGACY_CLIENT_ASSERTED-as-authoritative remain.

**Conclusion:** no route trusts a browser actor as authoritative today. This sprint formalizes the
server-derived identity into a canonical `OperatorContext`, adds the authorization decision seam,
emits canonical administrative audit, and hardens the paths against future regressions
(`assertNoClientActor`).
