// Actor context seam (CONSOLE-FOUNDATION-A, Stage 12 — prepare for SECURITY-A0).
//
// This sprint does NOT implement verified attribution or the canonical audit
// spine. It defines the SHAPE so later sprints don't have to redesign the
// foundation, and — critically — it forbids the insecure patterns the audit
// found (client-supplied moderator_id / operator_id / X-Operator).
//
// Rules encoded here:
//  * The foundation NEVER fabricates an operator (no `operator = "admin"`).
//  * The foundation NEVER trusts a browser-supplied actor identity.
//  * Actor identity is resolved server-side from the verified operator session.
//  * `publicActor` (official-identity delegation, ADR-0007) is reserved and
//    always null in this sprint — no silent impersonation is representable.

import type { ConsoleOperator } from "@/types/auth";

export interface ActorContext {
  /** Real operator resolved from the verified Gateway session (never a string). */
  readonly operatorId: string;
  readonly operatorDisplayName: string;
  /** Reserved for ADR-0007 delegation. ALWAYS null until CONSOLE-IDENTITY-A. */
  readonly publicActor: null;
  /** Origin marker for future audit events. */
  readonly origin: "insight-console";
  readonly correlationId: string | null;
}

/**
 * Build an actor context from a *server-verified* operator only. The foundation
 * has no read that needs mutation attribution yet; this exists so SECURITY-A0
 * can attach canonical audit without touching adapters/registries/snapshot.
 */
export function actorFromOperator(
  operator: ConsoleOperator,
  correlationId: string | null,
): ActorContext {
  return {
    operatorId: operator.id,
    operatorDisplayName: operator.displayName,
    publicActor: null,
    origin: "insight-console",
    correlationId,
  };
}

/**
 * Explicit guard documenting the forbidden pattern. Any future code tempted to
 * read an actor from the request body/headers must call through here and get a
 * hard rejection instead — keeping the insecure path un-reintroducible.
 */
export function rejectClientAssertedActor(field: string): never {
  throw new Error(
    `client-asserted actor identity is forbidden (field: ${field}); ` +
      `resolve the operator from the verified session (SECURITY-A0)`,
  );
}
