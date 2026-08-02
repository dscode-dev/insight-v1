// Administrative Audit Writer (CONSOLE-SECURITY-A0, Stage 8/9). SERVER-ONLY.
//
// Consistency model (honest — no invented atomicity across distributed services):
//   * Audit INTENT/DECISION is written before the mutation (AUTHORIZED/DENIED).
//   * Audit OUTCOME is written after the mutation (COMPLETED/FAILED/CANCELLED),
//     correlated by correlationId.
//   * A write NEVER silently swallows failure: on append failure OR a non-durable
//     store, the result carries `reconciliationNeeded:true` and observability
//     emits `audit_write_failed` / `audit_reconciliation_needed`.
//   * We do NOT claim exactly-once. The Postgres store dedupes on event_id
//     (idempotent append) so a retried request does not double-write the same
//     event id.
//
// Reusable by moderation, publication, identity delegation, agent admin, the
// future Operation Service and Executor. No domain-specific fields in the core.

import type { AuthorizationDecision } from "@/lib/control-plane/security/authorization";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";
import {
  buildAuditEvent,
  type AdministrativeAuditEvent,
  type AuditStatus,
  type BuildAuditArgs,
} from "@/lib/control-plane/security/audit/model";
import { getAuditRepository } from "@/lib/control-plane/security/audit/factory";
import { observeSecurity } from "@/lib/control-plane/security/observability";

export interface AuditWriteResult {
  readonly eventId: string;
  readonly persisted: boolean;
  readonly durable: boolean;
  readonly reconciliationNeeded: boolean;
}

async function record(args: BuildAuditArgs): Promise<AuditWriteResult> {
  const repo = getAuditRepository();
  const event: AdministrativeAuditEvent = buildAuditEvent(args);
  const fields = {
    operatorId: args.operator.operatorId,
    capability: args.capability,
    correlationId: args.operator.correlationId,
    durable: repo.durable,
  };
  try {
    await repo.append(event);
    observeSecurity("audit_write_succeeded", fields);
    if (!repo.durable) {
      // Persisted, but the store is not durable → reconciliation still needed.
      observeSecurity("audit_reconciliation_needed", fields);
    }
    return { eventId: event.eventId, persisted: true, durable: repo.durable, reconciliationNeeded: !repo.durable };
  } catch {
    observeSecurity("audit_write_failed", fields);
    observeSecurity("audit_reconciliation_needed", fields);
    return { eventId: event.eventId, persisted: false, durable: repo.durable, reconciliationNeeded: true };
  }
}

function statusFor(d: AuthorizationDecision): AuditStatus {
  return d.allowed ? "AUTHORIZED" : "DENIED";
}

export const AdministrativeAudit = {
  /** Emit the authorization decision (AUTHORIZED | DENIED). Write before mutation. */
  decision(
    operator: OperatorContext,
    d: AuthorizationDecision,
    extra: { target?: AdministrativeAuditEvent["target"]; reason?: string | null; metadata?: Record<string, unknown> } = {},
  ): Promise<AuditWriteResult> {
    return record({
      operator,
      capability: d.capability,
      status: statusFor(d),
      authorization: d,
      target: extra.target,
      reason: extra.reason ?? null,
      metadata: extra.metadata,
    });
  },

  /** Emit the outcome (COMPLETED | FAILED | CANCELLED | STARTED). Write after mutation. */
  outcome(
    operator: OperatorContext,
    d: AuthorizationDecision,
    status: Extract<AuditStatus, "STARTED" | "COMPLETED" | "FAILED" | "CANCELLED">,
    extra: {
      target?: AdministrativeAuditEvent["target"];
      errorCode?: string | null;
      retryable?: boolean;
      reason?: string | null;
      metadata?: Record<string, unknown>;
    } = {},
  ): Promise<AuditWriteResult> {
    return record({
      operator,
      capability: d.capability,
      status,
      authorization: d,
      target: extra.target,
      errorCode: extra.errorCode ?? null,
      retryable: extra.retryable ?? false,
      reason: extra.reason ?? null,
      metadata: extra.metadata,
    });
  },

  /** Raw record for callers that need a specific transition. */
  record,
};
