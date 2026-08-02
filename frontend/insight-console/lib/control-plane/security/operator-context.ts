// Canonical server-owned Operator Context (CONSOLE-SECURITY-A0, Stage 2).
// SERVER-ONLY.
//
// The single source of trusted administrative identity. Built ONLY from a
// server-verified operator session (Gateway `/v1/operator/auth/me`). The browser
// may request an action; it may NEVER declare who the operator is. Fields that
// the current auth contract does not expose are modeled as `null` — never
// fabricated.
//
// Honest provenance of each field is documented inline. Notably:
//  * `sessionId` = SHA-256 of the opaque session token — this is the REAL
//    server-side session key (the Gateway stores `token_hash = sha256(token)` in
//    operator_sessions). It is NOT the secret token and NOT the correlation id.
//  * `authStrength`, `authenticatedAt` are UNKNOWN (the /me contract omits them).

import { createHash } from "node:crypto";

import { ConsoleApiError } from "@/lib/admin-api";
import { currentOperator, readSessionCookie } from "@/lib/session";
import type { ConsoleOperator, Permission, Role } from "@/types/auth";
import type { DelegationContext } from "@/lib/control-plane/security/delegation";

export interface OperatorContext {
  /** Verified operator id (from the Gateway session). Always present. */
  readonly operatorId: string;
  readonly operatorDisplayName: string;
  /** Gateway-owned username, when present. Used for upstream compatibility
   * bridges (e.g. moderator_id) — always server-derived, never client-supplied. */
  readonly operatorUsername: string | null;
  /**
   * Effective OPERATIONAL IDENTITY id — the identity under which the action is
   * authored. This is now the OUTPUT of server-side resolution, not a structural
   * alias: it DEFAULTS to the operator's own identity (identityId == operatorId,
   * identityKind == "operator") and only DIFFERS under an active, Gateway-
   * authorized delegation (CONSOLE-IDENTITY-A). The operator is never dropped.
   */
  readonly identityId: string;
  /** operator | official_identity | agent. Default "operator" (self). */
  readonly identityKind: "operator" | "official_identity" | "agent";
  /** What the public surface may render (ADR-0007). null unless delegated. */
  readonly publicActor: string | null;
  /** Real session key = sha256(token). Non-secret, distinct from correlationId. */
  readonly sessionId: string;
  readonly roles: Role[];
  readonly permissions: Permission[];
  /** UNKNOWN in the current auth contract — never fabricated. */
  readonly authStrength: null;
  /** Real delegation context (resolved server-side via the Gateway authority).
   * null = acting as self (the default, backward-compatible path). */
  readonly delegation: DelegationContext | null;
  readonly correlationId: string | null;
  readonly requestId: string | null;
  /** UNKNOWN — the /me contract does not expose an authenticated-at claim. */
  readonly authenticatedAt: null;
  readonly source: "insight-console";
}

function sessionKey(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

function build(
  operator: ConsoleOperator,
  token: string,
  correlationId: string | null,
  requestId: string | null,
): OperatorContext {
  return Object.freeze({
    operatorId: operator.id,
    operatorDisplayName: operator.displayName,
    operatorUsername: operator.username ?? null,
    // Default (self) resolution: identity == operator. Not an alias — this is the
    // resolution output for the no-delegation path; withResolvedIdentity() swaps
    // it for a delegated subject after the Gateway authorizes a grant.
    identityId: operator.id,
    identityKind: "operator",
    publicActor: null,
    sessionId: sessionKey(token),
    roles: [operator.role],
    permissions: operator.permissions.slice(),
    authStrength: null,
    delegation: null,
    correlationId,
    requestId,
    authenticatedAt: null,
    source: "insight-console",
  });
}

/**
 * CONSOLE-IDENTITY-A — return a NEW OperatorContext with the effective identity +
 * delegation resolved server-side by the Gateway authority. The operator is ALWAYS
 * preserved (never replaced). Pure/additive: takes an already-resolved identity so
 * it is safe to unit-test without a Gateway call.
 */
export function withResolvedIdentity(
  base: OperatorContext,
  resolved: {
    identityId: string;
    identityKind: "operator" | "official_identity" | "agent";
    publicActor: string | null;
    delegation: DelegationContext | null;
  },
): OperatorContext {
  // Invariant: the authenticated operator is never dropped by delegation.
  if (resolved.delegation && resolved.delegation.operatorId !== base.operatorId) {
    throw new Error("delegation operator does not match the authenticated operator (forbidden)");
  }
  return Object.freeze({ ...base, ...resolved });
}

/**
 * Pure, testable builder: construct an OperatorContext from an already-verified
 * operator + the explicit session token + request. No cookie/Gateway access, so
 * it is safe to unit-test. The session id derives from the real token.
 */
export function buildOperatorContext(operator: ConsoleOperator, token: string, req: Request): OperatorContext {
  const requestId = req.headers.get("x-request-id");
  const correlationId = req.headers.get("x-correlation-id") ?? requestId;
  return build(operator, token, correlationId, requestId);
}

/**
 * Build an OperatorContext from an ALREADY server-verified operator (e.g. a route
 * that already called `requireOperator()`), avoiding a second Gateway round-trip.
 * The session id still derives from the real cookie token (server-side).
 */
export function operatorContextFromOperator(operator: ConsoleOperator, req: Request): OperatorContext {
  return buildOperatorContext(operator, readSessionCookie() ?? "", req);
}

/**
 * The single canonical resolver. Every administrative route resolves identity
 * here — routes never interpret claims independently. Throws
 * ConsoleApiError(401) when the session is missing/invalid.
 */
export async function resolveOperatorContext(req: Request): Promise<OperatorContext> {
  const token = readSessionCookie();
  if (!token) {
    throw new ConsoleApiError(401, "unauthenticated", { upstreamCode: "no_session" });
  }
  const operator = await currentOperator(); // verified server-side via Gateway
  if (!operator) {
    throw new ConsoleApiError(401, "unauthenticated", { upstreamCode: "session_invalid" });
  }
  const requestId = req.headers.get("x-request-id");
  // correlationId links a chain; defaults to the request id at the chain root
  // but is a DISTINCT concept (a caller may pass an existing chain id).
  const correlationId = req.headers.get("x-correlation-id") ?? requestId;
  return build(operator, token, correlationId, requestId);
}

/**
 * Guard: reject any attempt to treat a browser-supplied actor field as
 * authoritative. Use in routes that historically accepted such fields.
 */
export function assertNoClientActor(body: Record<string, unknown> | undefined): void {
  if (!body) return;
  for (const field of [
    "operator_id", "operatorId", "moderator_id", "moderatorId", "actor_id", "actorId", "act_as_user_id",
    // CONSOLE-IDENTITY-A — identity/delegation/public-actor are resolved
    // server-side by the Gateway; a browser-supplied value is never authoritative.
    "identity_id", "identityId", "delegation", "delegation_id", "delegationId",
    "public_actor", "publicActor", "subject_id", "subjectId",
  ]) {
    if (field in body) {
      // We do not throw (backward-compat): the value is simply IGNORED for
      // authoritative attribution. Observability records the attempt.
      delete (body as Record<string, unknown>)[field];
    }
  }
}
