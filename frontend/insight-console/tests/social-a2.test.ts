// CONSOLE-SOCIAL-A2 — capabilities, adapter routing, privacy regression.

import { afterEach, describe, expect, it, vi } from "vitest";

import { CapabilityRegistry } from "@/lib/control-plane/registries/capabilities";
import { authorize } from "@/lib/control-plane/security/authorization";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";
import type { Permission, Role } from "@/types/auth";

function op(permissions: Permission[], roles: Role[] = ["Operations"]): OperatorContext {
  return {
    operatorId: "op-1", operatorDisplayName: "Op", operatorUsername: "op", identityId: "op-1",
    sessionId: "s".repeat(64), roles, permissions, authStrength: null, identityKind: "operator", publicActor: null, delegation: null,
    correlationId: "c", requestId: "r", authenticatedAt: null, source: "insight-console",
  };
}

describe("A2 capabilities + authorization", () => {
  it("registers all A2 investigation capabilities with evidence", () => {
    for (const id of [
      "social.community.read", "social.relationship.read", "social.boost.read",
      "social.save.read", "social.investigation.read",
      "trust.report.read", "trust.moderation.read", "audit.event.read",
    ]) {
      expect(CapabilityRegistry.isValidId(id)).toBe(true);
      expect(CapabilityRegistry.get(id)?.evidence.length).toBeGreaterThan(0);
    }
  });
  it("fail-closed authorization for trust reads", () => {
    expect(authorize(op(["feed.read"]), "trust.report.read", "feed.read").allowed).toBe(true);
    expect(authorize(op([]), "trust.report.read", "feed.read").reasonCode).toBe("denied_permission_missing");
  });
});

describe("A2 adapter routing (browser never reaches Social)", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("targets the gateway social read plane for investigation reads", async () => {
    process.env.ADMIN_API_BASE_URL = "http://gw.test/v1";
    process.env.ADMIN_API_INTERNAL_TOKEN = "svc";
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((u: unknown) => { calls.push(String(u)); return Promise.resolve(new Response("{}", { status: 200 })); }));
    const ctx = { operatorToken: "t", correlationId: "c" };
    await SocialControlPlane.listComments(ctx, { post_id: "p" });
    await SocialControlPlane.relationships(ctx, "user", "u");
    await SocialControlPlane.timeline(ctx, "post", "p");
    await SocialControlPlane.listBoosts(ctx, { status: "active" });
    await SocialControlPlane.listCommunities(ctx);
    expect(calls.some((c) => c.includes("/console/social/comments"))).toBe(true);
    expect(calls.some((c) => c.includes("/console/social/relationships"))).toBe(true);
    expect(calls.some((c) => c.includes("/console/social/timeline"))).toBe(true);
    expect(calls.some((c) => c.includes("/console/social/boosts"))).toBe(true);
    expect(calls.some((c) => c.includes("/console/social/communities"))).toBe(true);
    delete process.env.ADMIN_API_BASE_URL; delete process.env.ADMIN_API_INTERNAL_TOKEN;
  });

  it("REGRESSION: adapter exposes NO individual-saver reader (privacy is structural)", () => {
    const methods = Object.keys(SocialControlPlane);
    expect(methods.some((m) => /saver|savedby|savelist|whosaved/i.test(m))).toBe(false);
  });
});
