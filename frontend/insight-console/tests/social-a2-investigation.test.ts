// CONSOLE-SOCIAL-A2 — InvestigationService + TimelineService composition tests.
// Domain adapters are mocked to prove partial-failure isolation + provenance.

import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/control-plane/adapters/social", () => ({
  SocialControlPlane: {
    getUser: vi.fn(async () => ({ identity: { id: "u1" } })),
    timeline: vi.fn(async () => ({ items: [{ id: "e1", at: "2026-01-01T00:00:00Z", kind: "post_created", target: { type: "post", id: "p1" } }] })),
    relationships: vi.fn(async () => ({ relationships: [{ type: "follow", direction: "inbound", target: { type: "user", id: "u2" } }] })),
    listBoosts: vi.fn(async () => ({ items: [] })),
    getAgent: vi.fn(), getPost: vi.fn(), getComment: vi.fn(), getCommunity: vi.fn(),
  },
}));
vi.mock("@/lib/control-plane/adapters/trust-safety", () => ({
  GatewayTrustSafety: {
    forTarget: vi.fn(async () => { throw new Error("moderation source down"); }),
    reports: vi.fn(async () => ({ reports: [] })),
    actions: vi.fn(async () => ({ actions: [] })),
  },
}));
vi.mock("@/lib/control-plane/security/audit/factory", () => ({
  getAuditRepository: () => ({
    query: vi.fn(async () => ({
      items: [{ eventId: "a1", occurredAt: "2026-01-02T00:00:00Z", action: { capability: "social.post.read" }, outcome: { status: "COMPLETED" }, target: { resourceId: "u1", resourceType: "user" }, correlationId: "c" }],
    })),
  }),
}));

const ctx = { operatorToken: "t", correlationId: "c" };

describe("InvestigationService", () => {
  it("isolates a failing source as an unavailable panel (never fake-complete); partial=true", async () => {
    const { InvestigationService } = await import("@/lib/control-plane/services/investigation");
    const r = await InvestigationService.investigate(ctx, "user", "u1");
    expect(r.partial).toBe(true);
    expect(r.panels.trust_safety.state).toBe("unavailable"); // failed but present, not omitted
    expect(r.panels.summary.state).toBe("available");
    expect(r.panels.relationships.state).toBe("available");
    expect(r.panels.administrative_audit.state).toBe("available");
    expect(r.sources.find((s) => s.panel === "trust_safety")?.source).toBe("insight-gateway");
    expect(r.sources.find((s) => s.panel === "administrative_audit")?.source).toContain("operator_audit_log");
  });
});

describe("TimelineService", () => {
  it("tags provenance per source and represents a failed source honestly", async () => {
    const { TimelineService } = await import("@/lib/control-plane/services/investigation");
    const t = await TimelineService.timeline(ctx, "user", "u1");
    const provs = new Set(t.items.map((i) => i.provenance));
    expect(provs.has("DURABLE_ROW_PROJECTION")).toBe(true);
    expect(provs.has("ADMINISTRATIVE_AUDIT")).toBe(true);
    expect(t.partial).toBe(true); // moderation source failed
    expect(t.sources.some((s) => s.state === "unavailable")).toBe(true);
    for (let i = 1; i < t.items.length; i++) expect(t.items[i - 1]!.at >= t.items[i]!.at).toBe(true); // desc order
  });
});
