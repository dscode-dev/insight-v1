// Administrative request context (CONSOLE-SECURITY-A0, Stage 3). SERVER-ONLY.
//
// Consolidates the trusted OperatorContext with safe correlation metadata and
// keeps the five identifiers DISTINCT (never collapsed):
//   requestId    — one HTTP request
//   correlationId — links a distributed administrative action chain
//   sessionId    — the authenticated session (in actor; sha256(token))
//   operationId  — the future durable Operation domain (NOT set here)
//   auditEventId — one audit record (assigned by the audit writer)

import type { EnvironmentId } from "@/lib/control-plane/types";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";
import { resolveOperatorContext } from "@/lib/control-plane/security/operator-context";

export type SourceSurface =
  | "moderation"
  | "data-intelligence"
  | "control-panel"
  | "publication"
  | "platform"
  | "audit";

export interface AdministrativeRequestContext {
  readonly actor: OperatorContext;
  readonly correlationId: string | null;
  readonly requestId: string | null;
  readonly occurredAt: string;
  readonly sourceSurface: SourceSurface;
  readonly environmentContext: EnvironmentId | null;
}

/**
 * Resolve the full administrative request context for a mutation route. The
 * actor is server-verified; correlation/request ids come from headers; the
 * surface + target environment are supplied by the route.
 */
export async function resolveAdminRequestContext(
  req: Request,
  sourceSurface: SourceSurface,
  environmentContext: EnvironmentId | null = null,
): Promise<AdministrativeRequestContext> {
  const actor = await resolveOperatorContext(req);
  return Object.freeze({
    actor,
    correlationId: actor.correlationId,
    requestId: actor.requestId,
    occurredAt: new Date().toISOString(),
    sourceSurface,
    environmentContext,
  });
}
