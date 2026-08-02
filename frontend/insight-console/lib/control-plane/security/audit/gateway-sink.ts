// Gateway audit sink (CONSOLE-SECURITY-A1). SERVER-ONLY.
//
// The DURABLE primary audit path: a typed adapter behind the Control Plane
// boundary that writes canonical events to the Gateway ingest endpoint
// (POST /v1/console/audit/events → operator_audit_log) and reads them back
// (GET /v1/console/audit/events). Auth: the Console service token (added by
// adminFetch) + the verified operator session Bearer (forwarded server-side).
// Operator identity is derived by the Gateway from the session — never sent in
// the body. No secrets serialized; bounded timeout; one safe retry; idempotent.

import { randomUUID } from "node:crypto";

import { adminFetch, ConsoleApiError } from "@/lib/admin-api";
import { readSessionCookie } from "@/lib/session";
import { observeSecurity } from "@/lib/control-plane/security/observability";
import type { AdministrativeAuditEvent } from "@/lib/control-plane/security/audit/model";
import type {
  AuditPage,
  AuditQueryFilter,
  AuditRepository,
} from "@/lib/control-plane/security/audit/repository";

const INGEST_PATH = "/v1/console/audit/events";
const TIMEOUT_MS = 4000;

interface IngestBody {
  correlation_id: string | null;
  request_id: string | null;
  capability: string;
  status: string;
  target: {
    environment_id: string | null;
    service_id: string | null;
    resource_type: string | null;
    resource_id: string | null;
  };
  authorization: { decision: string; reason_code: string; policy_source: string };
  reason: string | null;
  metadata: Record<string, unknown>;
  idempotency_key: string;
  // CONSOLE-IDENTITY-A — a REFERENCE only. identity_id / subject / public_actor are
  // NEVER sent from here; the Gateway derives them from its authoritative grant
  // store. Null → the operator's own identity (default, backward-compatible).
  delegation_id: string | null;
}

export function toIngestBody(e: AdministrativeAuditEvent, idempotencyKey: string): IngestBody {
  return {
    correlation_id: e.correlationId,
    request_id: e.requestId,
    capability: e.action.capability,
    status: e.outcome.status,
    target: {
      environment_id: e.target.environmentId,
      service_id: e.target.serviceId,
      resource_type: e.target.resourceType,
      resource_id: e.target.resourceId,
    },
    authorization: {
      decision: e.authorization.decision,
      reason_code: e.authorization.reasonCode,
      policy_source: e.authorization.policySource,
    },
    reason: e.context.reason,
    metadata: e.context.metadata,
    idempotency_key: idempotencyKey,
    delegation_id: e.delegation.grantId,
  };
}

/** The durable, Gateway-backed canonical audit repository. */
export class GatewayAuditRepository implements AuditRepository {
  readonly kind = "postgres" as const; // durable, Gateway/Postgres-backed
  readonly durable = true;

  async append(event: AdministrativeAuditEvent): Promise<void> {
    // One idempotency key per submission, stable across the internal retry.
    const idempotencyKey = randomUUID();
    const body = toIngestBody(event, idempotencyKey);
    const operatorToken = readSessionCookie() ?? undefined;
    const attempt = async (): Promise<Response> =>
      adminFetch(INGEST_PATH, {
        method: "POST",
        body,
        operatorToken,
        correlationId: event.correlationId ?? undefined,
        timeoutMs: TIMEOUT_MS,
      });

    let res: Response;
    try {
      res = await attempt();
      // Retry once on a transport/5xx failure (same idempotency key ⇒ no dup).
      if (res.status >= 500) res = await attempt();
    } catch {
      res = await attempt();
    }

    if (res.status === 201 || res.status === 200) {
      observeSecurity("audit_write_succeeded", {
        capability: event.action.capability,
        correlationId: event.correlationId,
        durable: true,
      });
      return;
    }
    // Non-persisted ⇒ throw so the writer records reconciliationNeeded honestly.
    throw new ConsoleApiError(res.status, "audit_ingest_failed");
  }

  async query(filter: AuditQueryFilter): Promise<AuditPage> {
    const params = new URLSearchParams();
    if (filter.correlationId) params.set("correlation_id", filter.correlationId);
    if (filter.operator) params.set("operator", filter.operator);
    if (filter.capability) params.set("capability", filter.capability);
    if (filter.service) params.set("service", filter.service);
    if (filter.environment) params.set("environment", filter.environment);
    if (filter.resourceId) params.set("resource_id", filter.resourceId);
    if (filter.outcome) params.set("outcome", filter.outcome);
    if (filter.since) params.set("since", filter.since);
    if (filter.until) params.set("until", filter.until);
    params.set("limit", String(filter.limit ?? 50));
    const qs = params.toString();
    const res = await adminFetch(`${INGEST_PATH}?${qs}`, {
      operatorToken: readSessionCookie() ?? undefined,
      timeoutMs: TIMEOUT_MS,
    });
    if (!res.ok) throw new ConsoleApiError(res.status, "audit_read_failed");
    const body = (await res.json()) as { items?: unknown[] };
    const items = Array.isArray(body.items) ? body.items.map(projectEvent) : [];
    // Gateway read is offset/limit; cursor pagination is a future extension.
    return { items, nextCursor: null };
  }

  async getById(eventId: string): Promise<AdministrativeAuditEvent | null> {
    // The Gateway read has no by-id filter yet; scan a bounded recent window.
    const page = await this.query({ limit: 200 });
    return page.items.find((e) => e.eventId === eventId) ?? null;
  }
}

// Project the Gateway read row back into the canonical shape. Fields the minimal
// spine does not round-trip (roles, delegation, authStrength) are defaulted.
function projectEvent(raw: unknown): AdministrativeAuditEvent {
  const r = (raw ?? {}) as Record<string, unknown>;
  const target = (r["target"] ?? {}) as Record<string, unknown>;
  const authz = (r["authorization"] ?? {}) as Record<string, unknown>;
  const outcome = (r["outcome"] ?? {}) as Record<string, unknown>;
  const s = (v: unknown): string | null => (typeof v === "string" && v !== "" ? v : null);
  const capability = String(r["capability"] ?? r["event_type"] ?? "");
  const [domain = "", resource = "", action = ""] = capability.split(".");
  const operatorId = String(r["operator_id"] ?? "");
  // CONSOLE-IDENTITY-A — the Gateway now round-trips identity + delegation +
  // public_actor. Backward-compat: NULL identity_id → identity == operator.
  const identityId = s(r["identity_id"]) ?? operatorId;
  const del = (r["delegation"] ?? null) as Record<string, unknown> | null;
  return {
    eventId: String(r["event_id"] ?? ""),
    occurredAt: String(r["occurred_at"] ?? ""),
    correlationId: s(r["correlation_id"]),
    requestId: s(r["request_id"]),
    actor: {
      operatorId,
      identityId,
      publicActor: s(r["public_actor"]),
      sessionId: String(r["session_id"] ?? ""),
      roles: [],
      authStrength: null,
    },
    delegation: del
      ? {
          active: true,
          subjectType: s(del["subject_type"]),
          subjectId: s(del["subject_id"]),
          mode: null,
          reason: null,
          grantId: s(del["delegation_id"]),
        }
      : { active: false, subjectType: null, subjectId: null, mode: null, reason: null, grantId: null },
    action: { capability, domain, resource, action },
    target: {
      environmentId: s(target["environment_id"]),
      serviceId: s(target["service_id"]),
      resourceType: s(target["resource_type"]),
      resourceId: s(target["resource_id"]),
    },
    authorization: {
      decision: authz["decision"] === "allow" ? "allow" : "deny",
      reasonCode: String(authz["reason_code"] ?? ""),
      policySource: "",
    },
    outcome: { status: String(outcome["status"] ?? "") as AdministrativeAuditEvent["outcome"]["status"], errorCode: null, retryable: false },
    context: { reason: null, metadata: (r["metadata"] as Record<string, string | number | boolean | null>) ?? {} },
  };
}
