// CONSOLE-SECURITY-A1 — durable audit factory + gateway-sink mapping tests.

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { getAuditRepository, __resetAuditRepository } from "@/lib/control-plane/security/audit/factory";
import { GatewayAuditRepository } from "@/lib/control-plane/security/audit/gateway-sink";
import { InMemoryAuditRepository } from "@/lib/control-plane/security/audit/repository";
import { toIngestBody } from "@/lib/control-plane/security/audit/gateway-sink";
import { buildAuditEvent } from "@/lib/control-plane/security/audit/model";
import type { AuthorizationDecision } from "@/lib/control-plane/security/authorization";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";

const OP: OperatorContext = {
  operatorId: "op-1", operatorDisplayName: "Op", operatorUsername: "op", identityId: "op-1",
  sessionId: "s".repeat(64), roles: ["Operations"], permissions: [], authStrength: null,
  identityKind: "operator",
  publicActor: null,
  delegation: null, correlationId: "corr-1", requestId: "req-1", authenticatedAt: null, source: "insight-console",
};
const ALLOW: AuthorizationDecision = {
  allowed: true, decision: "allow", reasonCode: "allowed_permission", policySource: "permission:feed.hide",
  capability: "social.content.moderate", requiredPermission: "feed.hide", target: {}, evaluatedAt: "t",
};

beforeEach(() => {
  __resetAuditRepository();
  delete process.env.CONSOLE_AUDIT_MODE;
  delete process.env.CONSOLE_AUDIT_DATABASE_URL;
});
afterEach(() => {
  __resetAuditRepository();
  delete process.env.CONSOLE_AUDIT_MODE;
  delete process.env.CONSOLE_AUDIT_DATABASE_URL;
});

describe("audit repository factory", () => {
  it("defaults to the DURABLE Gateway repository in production (no silent memory)", () => {
    const repo = getAuditRepository();
    expect(repo).toBeInstanceOf(GatewayAuditRepository);
    expect(repo.durable).toBe(true);
  });

  it("uses in-memory ONLY when explicitly requested", () => {
    process.env.CONSOLE_AUDIT_MODE = "memory";
    __resetAuditRepository();
    const repo = getAuditRepository();
    expect(repo).toBeInstanceOf(InMemoryAuditRepository);
    expect(repo.durable).toBe(false);
  });
});

describe("gateway ingest body mapping", () => {
  it("maps canonical fields, carries an idempotency key, and leaks no secret", () => {
    const event = buildAuditEvent({
      operator: OP, capability: "social.content.moderate", status: "AUTHORIZED",
      authorization: ALLOW,
      target: { environmentId: "google-cloud", serviceId: "social", resourceType: "post", resourceId: "p1" },
      metadata: { action: "remove_content", token: "SECRET" },
    });
    const body = toIngestBody(event, "idem-key-123");
    expect(body.capability).toBe("social.content.moderate");
    expect(body.status).toBe("AUTHORIZED");
    expect(body.correlation_id).toBe("corr-1");
    expect(body.target.service_id).toBe("social");
    expect(body.target.resource_id).toBe("p1");
    expect(body.authorization.decision).toBe("allow");
    expect(body.idempotency_key).toBe("idem-key-123");
    // The body never carries the operator id as authoritative identity (Gateway
    // derives it from the session) nor any secret.
    expect(JSON.stringify(body)).not.toContain("SECRET");
    expect(JSON.stringify(body)).not.toContain("operator_id");
  });

  it("distinct submissions get distinct idempotency keys (key != eventId)", () => {
    const e = buildAuditEvent({ operator: OP, capability: "social.content.moderate", status: "COMPLETED", authorization: ALLOW });
    const a = toIngestBody(e, "k1");
    const b = toIngestBody(e, "k2");
    expect(a.idempotency_key).not.toBe(b.idempotency_key);
    expect(a.idempotency_key).not.toBe(e.eventId); // idempotency key is not the event id
  });
});
