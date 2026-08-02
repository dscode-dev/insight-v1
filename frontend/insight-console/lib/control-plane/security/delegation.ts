// Delegation foundation (CONSOLE-SECURITY-A0, Stage 10). SERVER-ONLY.
//
// Prepares the SHAPE for explicit, authorized delegation (operator acts as an
// official identity / through an agent) WITHOUT activating it. This sprint MUST
// NOT implement Ninja User ↔ Agent linkage (that is CONSOLE-IDENTITY-A) and MUST
// NOT allow the browser to send `act_as_user_id` and become that user.
//
// Invariant (enforced by construction below):
//   THE AUTHENTICATED OPERATOR IS ALWAYS PRESERVED.
//   THE DELEGATED SUBJECT IS ADDITIVE CONTEXT, NEVER A REPLACEMENT.

export type DelegationMode = "act_as_identity" | "act_through_agent";
export type DelegationSubjectType = "official_identity" | "agent";

export interface DelegationContext {
  readonly delegationId: string;
  /** The REAL authenticated operator — can never be dropped. */
  readonly operatorId: string;
  readonly subjectType: DelegationSubjectType;
  readonly subjectId: string;
  readonly mode: DelegationMode;
  readonly scope: string[];
  readonly reason: string;
  readonly issuedAt: string;
  readonly expiresAt: string | null;
  readonly revokedAt: string | null;
}

/**
 * There is NO active delegation in this sprint. This resolver always returns
 * null. It exists so audit/authorization can already carry the field and later
 * sprints wire real grants without changing callers.
 */
export function resolveDelegation(): DelegationContext | null {
  return null;
}

/**
 * Reject any browser attempt to self-delegate. There is no code path in this
 * sprint that turns a client-supplied subject into an active delegation.
 */
export function rejectSelfDelegation(field: string): never {
  throw new Error(
    `self-delegation is forbidden (field: ${field}); delegation is an explicit, ` +
      `server-authorized grant that additively preserves the operator (CONSOLE-IDENTITY-A)`,
  );
}

/**
 * Enforce the preservation invariant on any future delegation object: the
 * operator must be present and distinct-from-or-owner-of the subject. Used by
 * tests now; used by real grants later.
 */
export function assertOperatorPreserved(d: DelegationContext, authenticatedOperatorId: string): void {
  if (!d.operatorId) throw new Error("delegation drops the operator (forbidden)");
  if (d.operatorId !== authenticatedOperatorId) {
    throw new Error("delegation operator does not match the authenticated operator (forbidden)");
  }
}
