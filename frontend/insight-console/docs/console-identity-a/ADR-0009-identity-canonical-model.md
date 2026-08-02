# ADR-0009 — CONSOLE-IDENTITY-A: canonical Operational Identity model (operationalizes ADR-0006/0007)

**Status:** Proposed (Stage 0 deliverable — awaiting approval before implementation).
**Supersedes-status:** operationalizes **ADR-0006 (identity attribution)** and **ADR-0007 (official
identity via delegation)** from *Proposed* → concrete, code-anchored model. Does NOT change
authentication, authorization, capabilities, SECURITY-A0, SOCIAL-B, Atlas, or the Investigation Plane.

---

## Context (from code)
- `OperatorContext` sets `identityId = operatorId` and `delegation = null` by construction
  (`operator-context.ts`).
- The `DelegationContext` shape + guards already exist and are inactive (`delegation.ts`).
- The canonical audit spine (`operator_audit_log`, Gateway 00006/00007) stores `operator_id` but has
  **no `identity_id` and no delegation columns**; the Console ingest body does not send an actor; reads
  project `identityId = operator_id`.
- There is **no official-identity/ownership domain**; "Ninja" is a Social **agent** (`agent_profiles`).
- Gateway is the **single authority** for operator credentials/sessions/roles/audit (00006 header).

## Decision — the canonical model

### Three distinct primitives (never collapsed)
1. **Operator** — the authenticated human principal. Owned by the **Gateway** (`operators`,
   `operator_sessions`). Immutable authority; IDENTITY-A does not touch it.
2. **Operational Identity** — the identity *under which an action is authored*. Default = the operator's
   own identity (`identity == operator`, retrocompatible). It becomes distinct ONLY under an active,
   authorized **delegation**. It is NOT a User, NOT an Agent, NOT a Service — it is the *authoring*
   identity, resolved server-side.
3. **Delegation** — an explicit, revocable, audited grant that lets an operator author actions **as** a
   designated subject (`official_identity` | `agent`) **while additively preserving the operator**.
   Never impersonation, never "become any user", never session switching.

### Resolution (server-side only)
```
Authenticated Operator (Gateway session)
        │  resolveOperatorContext()  — extended, never trusts the browser
        ▼
Effective Operational Identity = delegation.active ? delegation.subject : operator.identity
        │  (default path: identity == operator; unchanged behavior)
        ▼
DelegationContext (null | active grant, operator ALWAYS preserved)
        ▼
Audit event carries: operator + identity + delegation + intent/outcome + correlation
```
`identityId` stops being a literal alias: it is the **resolved effective identity id**. With no
delegation it equals the operator identity (so existing flows are byte-compatible).

### Dual attribution (ADR-0007 shape, now concrete)
On a delegated action the audit + (where authorized) public surface carry:
```
executed_by  = operator:<operatorId>     # the real operator — ALWAYS in audit
identity     = <effective identity id>   # authoring identity
public_actor = <subject>                 # only when authz + delegation permit (else null)
delegation   = { grantId, subjectType, subjectId, mode, reason, issuedAt, expiresAt, revokedAt }
```

## Responsibilities & ownership
| Concern | Owner | Notes |
|---|---|---|
| Operator credentials/sessions/roles | **Gateway** (unchanged) | authority; Console consumes `/me` |
| Durable audit spine (+ identity/delegation) | **Gateway** `operator_audit_log` | ADDITIVE columns (pattern of 00007) |
| Identity **resolution** (compose operator+delegation → effective identity) | **Console control-plane (server-side)** | where OperatorContext is already built |
| Delegation **grant store** (durable, revocable) | **Gateway** (recommended) | consistent with "Gateway is the authority for operator identity + audit". *Open decision — see below.* |
| Official-identity subject (Ninja) | **Social** (`agent_profiles`) | referenced as a subject only; no ownership model in IDENTITY-A |

**Open decision (flagged, not assumed):** the delegation grant store does not exist in code. This ADR
**recommends the Gateway** as owner (durable, same authority as operators/audit, additive migration).
The Console-owned audit store precedent (`CONSOLE_AUDIT_DATABASE_URL`) is the fallback. Final placement
is confirmed at approval, before Stage 3.

## Limits (explicit non-goals — enforced)
- No new auth/session/JWT/provider; no changes to `authorization.ts` or capabilities.
- No impersonation, acting-as, or session switching. Operator is never dropped
  (`assertOperatorPreserved`).
- No content ownership, no official publication, no signing, no approval chains, no multi-session, no
  federation, no Atlas/Explorer/IOC-Executor changes.
- Delegation V1 = explicit + revocable + audited only. The high-abuse `social.official_identity.publish`
  capability is *not activated* here (that is a later sprint); IDENTITY-A only makes the model
  representable and audited.

## Relation to existing invariants
- **Operator preserved** (I1), **no client actor** (I2), **authz unchanged** (I3), **single audit
  spine** (I4), **auth unchanged** (I5) — all preserved. New: identity resolved server-side (I6),
  delegation additive + audited (I7), full chain resolved server-side (I8).

## Migration impact (additive, backward-compatible)
- Gateway: `operator_audit_log += identity_id, delegation_subject_type, delegation_subject_id,
  delegation_mode, delegation_grant_id, delegation_reason, public_actor` (all NULLable). Ingest body +
  read projection extended. Old rows (NULL) → read defaults `identityId = operator_id` (compat).
- Console: `OperatorContext` gains resolved identity + real delegation; audit writer already carries the
  fields — only the sink/body/projection need the additive plumbing.
- No renames, no data rewrite, no removed columns.

## Prepares (without coupling) next sprints
- **AGENTS-A:** delegation `subjectType=agent` is generic; agent *ownership* stays out of scope.
- **SERVICE-OPS-A / IOC-EXECUTOR-A:** executed-by/identity/delegation on the audit event is exactly the
  provenance an executor needs; the model is executor-agnostic.

## Risks & mitigations
- Retrocompat of `identityId` under NULL `identity_id` → default-to-operator on read.
- Grant-store placement → decided at approval; recommended Gateway; additive either way.
- Fragmented durable authority (identity resolved in Console, stored in Gateway) → documented, bounded:
  authority stays Gateway; Console only resolves/composes.

## Acceptance (matches the sprint criteria)
`identityId` no longer a mere alias; resolution fully server-side; `Operator → Identity → Delegation →
Audit` implemented and auditable; no capability/authz/auth flow changed; audit spine single + intact;
existing tests green; next sprints prepared, not blocked.
