// CONSOLE-SECURITY-A0 — canonical audit model + writer + repository tests.

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { buildAuditEvent, safeMetadata } from "@/lib/control-plane/security/audit/model";
import { AdministrativeAudit } from "@/lib/control-plane/security/audit/writer";
import { getAuditRepository, __resetAuditRepository } from "@/lib/control-plane/security/audit/factory";
import { InMemoryAuditRepository } from "@/lib/control-plane/security/audit/repository";
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
const DENY: AuthorizationDecision = { ...ALLOW, allowed: false, decision: "deny", reasonCode: "denied_permission_missing" };

beforeEach(() => {
  delete process.env.CONSOLE_AUDIT_DATABASE_URL;
  process.env.CONSOLE_AUDIT_MODE = "memory"; // explicit dev/test store (never prod default)
  __resetAuditRepository();
});
afterEach(() => {
  delete process.env.CONSOLE_AUDIT_MODE;
  __resetAuditRepository();
});

describe("safeMetadata", () => {
  it("drops forbidden keys, drops non-scalars, truncates strings", () => {
    const meta = safeMetadata({
      action: "remove_content",
      token: "SECRET",
      authorization: "Bearer x",
      password: "p",
      nested: { a: 1 },
      count: 3,
      flag: true,
      long: "x".repeat(1000),
    });
    expect(meta.action).toBe("remove_content");
    expect(meta.count).toBe(3);
    expect(meta.flag).toBe(true);
    expect("token" in meta).toBe(false);
    expect("authorization" in meta).toBe(false);
    expect("password" in meta).toBe(false);
    expect("nested" in meta).toBe(false); // objects never dumped
    expect((meta.long as string).length).toBe(512);
  });
});

describe("buildAuditEvent", () => {
  it("preserves actor + correlation and never carries a token", () => {
    const e = buildAuditEvent({
      operator: OP, capability: "social.content.moderate", status: "AUTHORIZED",
      authorization: ALLOW, metadata: { token: "SECRET", action: "ban" },
    });
    expect(e.actor.operatorId).toBe("op-1");
    expect(e.actor.sessionId).toBe(OP.sessionId);
    expect(e.correlationId).toBe("corr-1");
    expect(e.action).toEqual({ capability: "social.content.moderate", domain: "social", resource: "content", action: "moderate" });
    expect(e.delegation.active).toBe(false);
    expect(JSON.stringify(e)).not.toContain("SECRET");
  });
});

describe("AdministrativeAudit writer (InMemory, non-durable)", () => {
  it("records AUTHORIZED then COMPLETED, preserving the correlation chain", async () => {
    await AdministrativeAudit.decision(OP, ALLOW, { metadata: { action: "remove_content" } });
    await AdministrativeAudit.outcome(OP, ALLOW, "COMPLETED", { metadata: { action: "remove_content" } });
    const repo = getAuditRepository() as InMemoryAuditRepository;
    const page = await repo.query({ correlationId: "corr-1" });
    expect(page.items.map((e) => e.outcome.status).sort()).toEqual(["AUTHORIZED", "COMPLETED"]);
    expect(page.items.every((e) => e.actor.operatorId === "op-1")).toBe(true);
  });

  it("records DENIED for a denied decision", async () => {
    const r = await AdministrativeAudit.decision(OP, DENY);
    expect(r.persisted).toBe(true);
    const page = await getAuditRepository().query({ capability: "social.content.moderate", outcome: "DENIED" });
    expect(page.items).toHaveLength(1);
    expect(page.items[0]!.authorization.decision).toBe("deny");
  });

  it("flags reconciliationNeeded when the store is not durable", async () => {
    const r = await AdministrativeAudit.decision(OP, ALLOW);
    expect(r.durable).toBe(false);
    expect(r.reconciliationNeeded).toBe(true); // in-memory ⇒ not durable, honest
  });

  it("does not persist tokens or objects", async () => {
    await AdministrativeAudit.outcome(OP, ALLOW, "COMPLETED", { metadata: { token: "SECRET", body: { x: 1 } } });
    const page = await getAuditRepository().query({});
    expect(JSON.stringify(page.items)).not.toContain("SECRET");
  });
});

describe("audit repository query/pagination", () => {
  it("filters and paginates deterministically", async () => {
    const repo = new InMemoryAuditRepository();
    for (let i = 0; i < 5; i++) {
      await repo.append(
        buildAuditEvent({
          operator: { ...OP, correlationId: `c-${i}` },
          capability: "social.content.moderate", status: "COMPLETED", authorization: ALLOW,
        }),
      );
    }
    const p1 = await repo.query({ limit: 2 });
    expect(p1.items).toHaveLength(2);
    expect(p1.nextCursor).not.toBeNull();
    const p2 = await repo.query({ limit: 2, cursor: p1.nextCursor });
    expect(p2.items).toHaveLength(2);
    // no overlap between pages
    const ids1 = new Set(p1.items.map((e) => e.eventId));
    expect(p2.items.some((e) => ids1.has(e.eventId))).toBe(false);
  });
});
