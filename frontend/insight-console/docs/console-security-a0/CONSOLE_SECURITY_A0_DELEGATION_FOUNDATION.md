# CONSOLE-SECURITY-A0 — Delegation Foundation

`lib/control-plane/security/delegation.ts`. Prepares the SHAPE for explicit, authorized delegation
WITHOUT activating it. This sprint does NOT implement Ninja User ↔ Agent linkage (CONSOLE-IDENTITY-A)
and does NOT allow `act_as_user_id` from the browser.

## Contract (`DelegationContext`)
`delegationId, operatorId, subjectType(official_identity|agent), subjectId,
mode(act_as_identity|act_through_agent), scope[], reason, issuedAt, expiresAt, revokedAt`.

## Invariant (enforced by construction + tests)
> THE AUTHENTICATED OPERATOR IS ALWAYS PRESERVED.
> THE DELEGATED SUBJECT IS ADDITIVE CONTEXT, NEVER A REPLACEMENT.

- `resolveDelegation()` — always `null` this sprint (no active delegation). `OperatorContext.delegation`
  is therefore always `null`; audit `delegation.active = false`.
- `rejectSelfDelegation(field)` — hard-throws; there is no path turning a client-supplied subject
  into an active delegation.
- `assertOperatorPreserved(d, authenticatedOperatorId)` — throws if the operator is dropped or does
  not match the authenticated operator (i.e. impersonation). Tested: preserved passes; dropped and
  mismatched throw.

## Why the audit model already carries delegation
Every canonical audit event includes a `delegation` block (inactive now). When CONSOLE-IDENTITY-A
wires real grants, the public actor may render as the official identity **while audit always
preserves the real operator** — no silent impersonation is representable, because the operator field
can never be replaced by the subject.
