# CONSOLE-SECURITY-A0 — Authorization Seam

`lib/control-plane/security/authorization.ts` — authorization is a **DECISION**, not a registry
lookup. The Capability Registry (CONSOLE-FOUNDATION-A) is descriptive; it MUST NOT grant a right.

## Contract
`authorize(operator: OperatorContext, capability: string, requiredPermission: Permission | null,
target?) → AuthorizationDecision`

`AuthorizationDecision = { allowed, decision: allow|deny, reasonCode, policySource, capability,
requiredPermission, target, evaluatedAt }`.

## Rules (reuse REAL platform policy; invent nothing)
1. **Capability presence is a precondition, not a grant.** Unknown capability ⇒
   `denied_capability_unsupported`.
2. **SuperAdmin** ⇒ allow (`allowed_superadmin`, `policySource: role:SuperAdmin`). This is the
   *existing* rule (`lib/operations-domain.ts` + Gateway `console/roles.go`), preserved + documented.
3. **Fail-closed:** a mutation with **no declared permission policy** ⇒ `denied_no_policy`.
4. Operator holds the required permission ⇒ allow (`allowed_permission`, `policySource:
   permission:<perm>`).
5. Otherwise ⇒ `denied_permission_missing`.

The `requiredPermission` is supplied by the use case from the **real** per-action policy (e.g.
moderation `ACTION_PERMISSION[action]` — `feed.hide`/`feed.restore`/`user.ban`/…). No permission is
invented; `OWNER ⇒ everything` is NOT assumed (only the explicit SuperAdmin rule exists).

## What this sprint does NOT do
- No new permissions. No policy engine. No per-resource ABAC. Those evolve behind this seam without
  rewriting use cases. Enforcement is applied at the BFF (defence-in-depth); services remain the
  ultimate authority.

## Tested
allow-by-permission · deny-missing · SuperAdmin-allow-without-perm · unsupported-capability-deny ·
mutation-no-policy fail-closed · **registered capability + missing permission ⇒ deny** (presence ≠
authorization).
