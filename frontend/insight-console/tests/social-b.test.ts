// CONSOLE-SOCIAL-B — enforcement plane: capability registration, fail-closed
// authorization, adapter command routing + structural actor-strip, no generic
// mutate/execute, read-only regressions preserved.

import { afterEach, describe, expect, it, vi } from "vitest";

import { CapabilityRegistry } from "@/lib/control-plane/registries/capabilities";
import { authorize } from "@/lib/control-plane/security/authorization";
import { SocialEnforcement } from "@/lib/control-plane/adapters/social-enforcement";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";
import type { Permission, Role } from "@/types/auth";

// Social enforcement goes through the Insight Control Plane now, and it
// authenticates with the operator's session cookie.
vi.mock("@/lib/session-cookie", () => ({
  SESSION_COOKIE: "insight_console_session",
  readSessionCookie: () => "op-tok",
}));


function op(permissions: Permission[], roles: Role[] = ["Operations"]): OperatorContext {
  return {
    operatorId: "op-1", operatorDisplayName: "Op", operatorUsername: "op", identityId: "op-1",
    sessionId: "s".repeat(64), roles, permissions, authStrength: null, identityKind: "operator", publicActor: null, delegation: null,
    correlationId: "c", requestId: "r", authenticatedAt: null, source: "insight-console",
  };
}

const COMMAND_CAPS = [
  "social.user.suspend", "social.user.ban",
  "social.content.hide", "social.content.restore",
  "social.agent.deactivate", "social.agent.reactivate",
  "trust.report.review", "trust.report.resolve", "trust.report.dismiss",
];

describe("B: capabilities + authorization", () => {
  it("registers every enforcement capability with evidence", () => {
    for (const id of COMMAND_CAPS) {
      expect(CapabilityRegistry.isValidId(id)).toBe(true);
      expect(CapabilityRegistry.get(id)?.evidence.length).toBeGreaterThan(0);
    }
  });

  it("classifies enforcement capabilities as mutations (high/approval)", () => {
    const ban = CapabilityRegistry.get("social.user.ban");
    expect(ban?.actionType).toBe("mutation");
    expect(ban?.approvalRequired).toBe(true);
  });

  it("fail-closed: missing permission is denied; SuperAdmin allowed", () => {
    expect(authorize(op([]), "social.user.ban", "user.ban").allowed).toBe(false);
    expect(authorize(op(["user.ban"]), "social.user.ban", "user.ban").allowed).toBe(true);
    expect(authorize(op([], ["SuperAdmin"]), "social.user.ban", "user.ban").allowed).toBe(true);
  });

  it("unregistered capability is denied (registry presence is a precondition)", () => {
    expect(authorize(op([], ["SuperAdmin"]), "social.user.delete", null).reasonCode).toBe(
      "denied_capability_unsupported",
    );
  });
});

describe("B: adapter command routing + actor-strip", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("targets typed gateway command paths with POST; NO actor in body", async () => {
    process.env.ADMIN_API_BASE_URL = "http://gw.test/v1";
    process.env.ADMIN_API_INTERNAL_TOKEN = "svc";
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn((u: unknown, init: RequestInit) => {
      calls.push({ url: String(u), init });
      return Promise.resolve(new Response(JSON.stringify({ ok: true, resulting_state: "banned" }), { status: 200 }));
    }));
    const ctx = { operatorToken: "t", correlationId: "c" };
    // A caller tries to smuggle actor identity — it must be stripped.
    await SocialEnforcement.banUser(ctx, "u1", { reason: "spam", operator_id: "spoof", moderator_id: "spoof" } as never);
    await SocialEnforcement.hidePost(ctx, "p1", { reason: "abuse" });
    await SocialEnforcement.reviewReport(ctx, "r1", { reason: "triage" });

    expect(calls[0]!.url).toContain("/console/social/users/u1/ban");
    expect(calls[0]!.init.method).toBe("POST");
    const body = JSON.parse(String(calls[0]!.init.body));
    expect(body.reason).toBe("spam");
    expect(body.operator_id).toBeUndefined();
    expect(body.moderator_id).toBeUndefined();
    expect(calls[1]!.url).toContain("/console/social/posts/p1/hide");
    expect(calls[2]!.url).toContain("/console/social/reports/r1/review");
    delete process.env.ADMIN_API_BASE_URL; delete process.env.ADMIN_API_INTERNAL_TOKEN;
  });

  it("exposes ONLY typed commands — no generic mutate/execute/proxy", () => {
    const keys = Object.keys(SocialEnforcement);
    expect(keys.some((k) => /mutate|execute|proxy|raw|sql|command$/i.test(k))).toBe(false);
    expect(keys).toContain("banUser");
    expect(keys).toContain("deactivateAgent");
  });

  it("REGRESSION: read adapter still exposes NO saver reader (A2 privacy preserved)", () => {
    const methods = Object.keys(SocialControlPlane);
    expect(methods.some((m) => /saver|savedby|savelist|whosaved/i.test(m))).toBe(false);
  });
});
