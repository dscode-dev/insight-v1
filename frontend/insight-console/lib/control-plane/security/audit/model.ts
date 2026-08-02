// Canonical Administrative Audit Event model (CONSOLE-SECURITY-A0, Stage 6).
//
// This is NOT an application log, NOT Control Plane observability, NOT an IOC
// operational event, NOT a domain event, NOT an Operation-lifecycle event. It is
// the tamper-evident administrative record answering WHO/WHAT/WHERE/WHICH
// RESOURCE/WHICH CAPABILITY/WHICH AUTHORIZATION/OUTCOME/WHY/CORRELATION.
//
// Schema is a SUPERSET-compatible extension of the Gateway's existing
// `operator_audit_log` (id/action/actor_id/actor_display_name/target/service/
// request_id/correlation_id/metadata/created_at) so it can federate into the one
// canonical spine (ADR-0005). No secrets, no tokens, no raw request bodies.

import { randomUUID } from "node:crypto";

import type { OperatorContext } from "@/lib/control-plane/security/operator-context";

export type AuditStatus =
  | "REQUESTED"
  | "AUTHORIZED"
  | "DENIED"
  | "STARTED"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type SafeMetaValue = string | number | boolean | null;

export interface AuditActor {
  readonly operatorId: string;
  /** Effective operational identity (== operatorId when acting as self). */
  readonly identityId: string;
  /** ADR-0007 public actor — what the public may see; null unless delegated. */
  readonly publicActor: string | null;
  readonly sessionId: string;
  readonly roles: string[];
  readonly authStrength: null;
}

export interface AuditDelegation {
  readonly active: boolean;
  readonly subjectType: string | null;
  readonly subjectId: string | null;
  readonly mode: string | null;
  readonly reason: string | null;
  readonly grantId: string | null;
}

export interface AdministrativeAuditEvent {
  readonly eventId: string;
  readonly occurredAt: string;
  readonly correlationId: string | null;
  readonly requestId: string | null;
  readonly actor: AuditActor;
  readonly delegation: AuditDelegation;
  readonly action: { capability: string; domain: string; resource: string; action: string };
  readonly target: {
    environmentId: string | null;
    serviceId: string | null;
    resourceType: string | null;
    resourceId: string | null;
  };
  readonly authorization: { decision: "allow" | "deny"; reasonCode: string; policySource: string };
  readonly outcome: { status: AuditStatus; errorCode: string | null; retryable: boolean };
  readonly context: { reason: string | null; metadata: Record<string, SafeMetaValue> };
}

// Keys that must NEVER appear in audit metadata.
const FORBIDDEN = /token|secret|password|cookie|authorization|credential|bearer|x-internal/i;

/** Sanitize caller-supplied metadata: safe scalar values only, forbidden keys
 * dropped, strings truncated. Never accepts raw bodies/objects. */
export function safeMetadata(input: Record<string, unknown> | undefined): Record<string, SafeMetaValue> {
  const out: Record<string, SafeMetaValue> = {};
  if (!input) return out;
  for (const [key, value] of Object.entries(input)) {
    if (FORBIDDEN.test(key)) continue;
    if (value === null) out[key] = null;
    else if (typeof value === "string") out[key] = value.slice(0, 512);
    else if (typeof value === "number" || typeof value === "boolean") out[key] = value;
    // objects/arrays/functions are intentionally dropped (no body dumping)
  }
  return out;
}

function parseCapability(capability: string): { domain: string; resource: string; action: string } {
  const [domain = "unknown", resource = "unknown", action = "unknown"] = capability.split(".");
  return { domain, resource, action };
}

export interface BuildAuditArgs {
  operator: OperatorContext;
  capability: string;
  status: AuditStatus;
  authorization: { decision: "allow" | "deny"; reasonCode: string; policySource: string };
  target?: AdministrativeAuditEvent["target"];
  errorCode?: string | null;
  retryable?: boolean;
  reason?: string | null;
  metadata?: Record<string, unknown>;
}

/** Build a canonical audit event from trusted server context. */
export function buildAuditEvent(args: BuildAuditArgs): AdministrativeAuditEvent {
  const parts = parseCapability(args.capability);
  const d = args.operator.delegation;
  return {
    eventId: randomUUID(),
    occurredAt: new Date().toISOString(),
    correlationId: args.operator.correlationId,
    requestId: args.operator.requestId,
    actor: {
      operatorId: args.operator.operatorId,
      identityId: args.operator.identityId,
      publicActor: args.operator.publicActor,
      sessionId: args.operator.sessionId,
      roles: args.operator.roles.slice(),
      authStrength: null,
    },
    delegation: {
      active: d !== null,
      subjectType: d?.subjectType ?? null,
      subjectId: d?.subjectId ?? null,
      mode: d?.mode ?? null,
      reason: d?.reason ?? null,
      grantId: d?.delegationId ?? null,
    },
    action: { capability: args.capability, ...parts },
    target: args.target ?? { environmentId: null, serviceId: null, resourceType: null, resourceId: null },
    authorization: {
      decision: args.authorization.decision,
      reasonCode: args.authorization.reasonCode,
      policySource: args.authorization.policySource,
    },
    outcome: {
      status: args.status,
      errorCode: args.errorCode ?? null,
      retryable: args.retryable ?? false,
    },
    context: { reason: args.reason ?? null, metadata: safeMetadata(args.metadata) },
  };
}
