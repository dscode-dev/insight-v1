// Audit persistence (CONSOLE-SECURITY-A0, Stage 7/8). SERVER-ONLY.
//
// Spine decision (evidence-based — see CONSOLE_SECURITY_A0_AUDIT_SPINE.md):
//   The canonical spine is the Gateway-owned `operator_audit_log` (insight_auth,
//   cloud Postgres), which the Console can currently only READ. The Console
//   cannot WRITE to it (no ingest endpoint). Target = EXTEND that spine. Until a
//   Gateway ingest endpoint ships, the Console persists its own canonical events
//   in a DURABLE Postgres store (config-gated by CONSOLE_AUDIT_DATABASE_URL),
//   using the SUPERSET-compatible schema so the two federate by correlation id.
//
// DURABILITY: Postgres when configured (durable). If unconfigured, an in-memory
// store is used and flagged `durable:false` — the writer + observability surface
// this honestly (never claims a log is durable audit). NEVER /tmp, NEVER JSON files.

import type { AdministrativeAuditEvent } from "@/lib/control-plane/security/audit/model";

export interface AuditQueryFilter {
  correlationId?: string;
  operator?: string;
  capability?: string;
  service?: string;
  environment?: string;
  resourceId?: string;
  outcome?: string;
  since?: string;
  until?: string;
  cursor?: string | null;
  limit?: number;
}

export interface AuditPage {
  items: AdministrativeAuditEvent[];
  nextCursor: string | null;
}

export interface AuditRepository {
  readonly kind: "postgres" | "memory";
  readonly durable: boolean;
  append(event: AdministrativeAuditEvent): Promise<void>;
  query(filter: AuditQueryFilter): Promise<AuditPage>;
  getById(eventId: string): Promise<AdministrativeAuditEvent | null>;
}

function clampLimit(limit: number | undefined): number {
  if (!limit || !Number.isFinite(limit)) return 50;
  return Math.max(1, Math.min(200, Math.floor(limit)));
}

// Deterministic keyset cursor over (occurredAt, eventId).
function encodeCursor(e: AdministrativeAuditEvent): string {
  return Buffer.from(`${e.occurredAt}|${e.eventId}`, "utf8").toString("base64url");
}
function decodeCursor(cursor: string | null | undefined): { occurredAt: string; eventId: string } | null {
  if (!cursor) return null;
  try {
    const [occurredAt, eventId] = Buffer.from(cursor, "base64url").toString("utf8").split("|");
    if (!occurredAt || !eventId) return null;
    return { occurredAt, eventId };
  } catch {
    return null;
  }
}

// ---- In-memory (tests + dev only; NOT durable) ----
export class InMemoryAuditRepository implements AuditRepository {
  readonly kind = "memory" as const;
  readonly durable = false;
  private readonly events: AdministrativeAuditEvent[] = [];

  async append(event: AdministrativeAuditEvent): Promise<void> {
    this.events.push(event);
  }

  async getById(eventId: string): Promise<AdministrativeAuditEvent | null> {
    return this.events.find((e) => e.eventId === eventId) ?? null;
  }

  async query(filter: AuditQueryFilter): Promise<AuditPage> {
    const limit = clampLimit(filter.limit);
    let rows = this.events
      .filter((e) => (filter.correlationId ? e.correlationId === filter.correlationId : true))
      .filter((e) => (filter.operator ? e.actor.operatorId === filter.operator : true))
      .filter((e) => (filter.capability ? e.action.capability === filter.capability : true))
      .filter((e) => (filter.service ? e.target.serviceId === filter.service : true))
      .filter((e) => (filter.environment ? e.target.environmentId === filter.environment : true))
      .filter((e) => (filter.resourceId ? e.target.resourceId === filter.resourceId : true))
      .filter((e) => (filter.outcome ? e.outcome.status === filter.outcome : true))
      .filter((e) => (filter.since ? e.occurredAt >= filter.since : true))
      .filter((e) => (filter.until ? e.occurredAt <= filter.until : true))
      // deterministic ordering: occurredAt desc, eventId desc
      .sort((a, b) => (b.occurredAt.localeCompare(a.occurredAt) || b.eventId.localeCompare(a.eventId)));

    const after = decodeCursor(filter.cursor);
    if (after) {
      rows = rows.filter(
        (e) =>
          e.occurredAt < after.occurredAt ||
          (e.occurredAt === after.occurredAt && e.eventId < after.eventId),
      );
    }
    const page = rows.slice(0, limit);
    const nextCursor = rows.length > limit && page.length > 0 ? encodeCursor(page[page.length - 1]!) : null;
    return { items: page, nextCursor };
  }
}

// ---- Postgres (durable; config-gated) ----
// Minimal structural type for the pg pool — avoids a compile-time @types/pg dep.
interface PgLike {
  query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
}

export class PostgresAuditRepository implements AuditRepository {
  readonly kind = "postgres" as const;
  readonly durable = true;
  private pool: PgLike | null = null;

  constructor(private readonly connectionString: string) {}

  private async db(): Promise<PgLike> {
    if (this.pool) return this.pool;
    const pg = (await import("pg")) as unknown as { Pool: new (c: { connectionString: string }) => PgLike };
    this.pool = new pg.Pool({ connectionString: this.connectionString });
    return this.pool;
  }

  async append(e: AdministrativeAuditEvent): Promise<void> {
    const db = await this.db();
    await db.query(
      `INSERT INTO control_plane_audit_event (
        event_id, occurred_at, correlation_id, request_id,
        actor_operator_id, actor_identity_id, actor_session_id, actor_roles,
        delegation_active, delegation_subject_type, delegation_subject_id, delegation_mode, delegation_grant_id,
        capability, action_domain, action_resource, action_action,
        target_environment_id, target_service_id, target_resource_type, target_resource_id,
        authz_decision, authz_reason_code, authz_policy_source,
        outcome_status, outcome_error_code, outcome_retryable,
        reason, metadata
      ) VALUES (
        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29
      ) ON CONFLICT (event_id) DO NOTHING`,
      [
        e.eventId, e.occurredAt, e.correlationId, e.requestId,
        e.actor.operatorId, e.actor.identityId, e.actor.sessionId, e.actor.roles,
        e.delegation.active, e.delegation.subjectType, e.delegation.subjectId, e.delegation.mode, e.delegation.grantId,
        e.action.capability, e.action.domain, e.action.resource, e.action.action,
        e.target.environmentId, e.target.serviceId, e.target.resourceType, e.target.resourceId,
        e.authorization.decision, e.authorization.reasonCode, e.authorization.policySource,
        e.outcome.status, e.outcome.errorCode, e.outcome.retryable,
        e.context.reason, JSON.stringify(e.context.metadata),
      ],
    );
  }

  async getById(eventId: string): Promise<AdministrativeAuditEvent | null> {
    const db = await this.db();
    const { rows } = await db.query(`SELECT * FROM control_plane_audit_event WHERE event_id = $1`, [eventId]);
    const row = rows[0];
    return row ? rowToEvent(row) : null;
  }

  async query(filter: AuditQueryFilter): Promise<AuditPage> {
    const db = await this.db();
    const limit = clampLimit(filter.limit);
    const where: string[] = [];
    const params: unknown[] = [];
    const eq = (col: string, val: string | undefined) => {
      if (val === undefined) return;
      params.push(val);
      where.push(`${col} = $${params.length}`);
    };
    eq("correlation_id", filter.correlationId);
    eq("actor_operator_id", filter.operator);
    eq("capability", filter.capability);
    eq("target_service_id", filter.service);
    eq("target_environment_id", filter.environment);
    eq("target_resource_id", filter.resourceId);
    eq("outcome_status", filter.outcome);
    if (filter.since) { params.push(filter.since); where.push(`occurred_at >= $${params.length}`); }
    if (filter.until) { params.push(filter.until); where.push(`occurred_at <= $${params.length}`); }
    const after = decodeCursor(filter.cursor);
    if (after) {
      params.push(after.occurredAt, after.eventId);
      where.push(`(occurred_at, event_id) < ($${params.length - 1}, $${params.length})`);
    }
    params.push(limit + 1);
    const sql = `SELECT * FROM control_plane_audit_event ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
      ORDER BY occurred_at DESC, event_id DESC LIMIT $${params.length}`;
    const { rows } = await db.query(sql, params);
    const events = rows.map(rowToEvent);
    const page = events.slice(0, limit);
    const nextCursor = events.length > limit && page.length > 0 ? encodeCursor(page[page.length - 1]!) : null;
    return { items: page, nextCursor };
  }
}

function str(v: unknown): string | null {
  return typeof v === "string" ? v : v == null ? null : String(v);
}

function rowToEvent(r: Record<string, unknown>): AdministrativeAuditEvent {
  const roles = Array.isArray(r["actor_roles"]) ? (r["actor_roles"] as unknown[]).map(String) : [];
  const meta = (typeof r["metadata"] === "object" && r["metadata"] !== null ? r["metadata"] : {}) as Record<string, string | number | boolean | null>;
  return {
    eventId: String(r["event_id"]),
    occurredAt: new Date(String(r["occurred_at"])).toISOString(),
    correlationId: str(r["correlation_id"]),
    requestId: str(r["request_id"]),
    actor: {
      operatorId: String(r["actor_operator_id"]),
      identityId: String(r["actor_identity_id"] ?? r["actor_operator_id"]),
      publicActor: str(r["actor_public_actor"]),
      sessionId: String(r["actor_session_id"]),
      roles,
      authStrength: null,
    },
    delegation: {
      active: Boolean(r["delegation_active"]),
      subjectType: str(r["delegation_subject_type"]),
      subjectId: str(r["delegation_subject_id"]),
      mode: str(r["delegation_mode"]),
      reason: null,
      grantId: str(r["delegation_grant_id"]),
    },
    action: {
      capability: String(r["capability"]),
      domain: String(r["action_domain"] ?? ""),
      resource: String(r["action_resource"] ?? ""),
      action: String(r["action_action"] ?? ""),
    },
    target: {
      environmentId: str(r["target_environment_id"]),
      serviceId: str(r["target_service_id"]),
      resourceType: str(r["target_resource_type"]),
      resourceId: str(r["target_resource_id"]),
    },
    authorization: {
      decision: r["authz_decision"] === "allow" ? "allow" : "deny",
      reasonCode: String(r["authz_reason_code"] ?? ""),
      policySource: String(r["authz_policy_source"] ?? ""),
    },
    outcome: {
      status: String(r["outcome_status"]) as AdministrativeAuditEvent["outcome"]["status"],
      errorCode: str(r["outcome_error_code"]),
      retryable: Boolean(r["outcome_retryable"]),
    },
    context: { reason: str(r["reason"]), metadata: meta },
  };
}

// Factory lives in ./factory.ts to avoid a cycle with the Gateway sink.
