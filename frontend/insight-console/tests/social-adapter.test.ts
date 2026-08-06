// CONSOLE-SOCIAL-A1 — Social adapter + capability/authorization tests.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The console reaches Social through the Insight Control Plane now, and
// that call authenticates with the operator's session cookie. Without a
// cookie every request short-circuits to 401 and every assertion below
// would fail for the wrong reason.
vi.mock("@/lib/session-cookie", () => ({
  SESSION_COOKIE: "insight_console_session",
  readSessionCookie: () => "op-tok",
}));

import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
import { ControlPlaneError } from "@/lib/control-plane/errors";
import { CapabilityRegistry } from "@/lib/control-plane/registries/capabilities";
import { authorize } from "@/lib/control-plane/security/authorization";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";
import type { Permission, Role } from "@/types/auth";

const ctx = { operatorToken: "op-tok", correlationId: "c1" };

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status }))));
}

beforeEach(() => {
  process.env.CONSOLE_API_BASE_URL = "http://control-plane.test:3002";
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_BASE_URL;
  delete process.env.ADMIN_API_INTERNAL_TOKEN;
});

describe("SocialControlPlane adapter", () => {
  it("returns parsed data on success + hits the gateway social read plane", async () => {
    mockFetch(200, { totals: { users: 3 }, source: "insight-social" });
    const data = (await SocialControlPlane.overview(ctx, "7d")) as { source: string };
    expect(data.source).toBe("insight-social");
    const url = String(vi.mocked(fetch).mock.calls[0]?.[0]);
    expect(url).toContain("/console/social/overview");
  });

  it("maps 503 → SERVICE_UNAVAILABLE (never an empty array)", async () => {
    mockFetch(503, { detail: "down" });
    await expect(SocialControlPlane.listPosts(ctx)).rejects.toMatchObject({ code: "SERVICE_UNAVAILABLE" });
  });

  it("maps 401 → UNAUTHORIZED and 404 → NOT_FOUND", async () => {
    mockFetch(401, {});
    await expect(SocialControlPlane.getUser(ctx, "x")).rejects.toBeInstanceOf(ControlPlaneError);
    await expect(SocialControlPlane.getUser(ctx, "x")).rejects.toMatchObject({ code: "UNAUTHORIZED" });
    mockFetch(404, {});
    await expect(SocialControlPlane.getPost(ctx, "x")).rejects.toMatchObject({ code: "NOT_FOUND" });
  });

  it("never serializes the service token into the thrown error", async () => {
    mockFetch(503, {});
    try {
      await SocialControlPlane.listUsers(ctx);
    } catch (e) {
      expect(JSON.stringify(e instanceof ControlPlaneError ? e.toShape() : e)).not.toContain("svc");
    }
  });
});

function op(permissions: Permission[], roles: Role[] = ["Operations"]): OperatorContext {
  return {
    operatorId: "op-1", operatorDisplayName: "Op", operatorUsername: "op", identityId: "op-1",
    sessionId: "s".repeat(64), roles, permissions, authStrength: null, identityKind: "operator", publicActor: null, delegation: null,
    correlationId: "c", requestId: "r", authenticatedAt: null, source: "insight-console",
  };
}

describe("social capabilities + authorization", () => {
  it("registers evidence-backed social read capabilities", () => {
    for (const id of ["social.overview.read", "social.activity.read", "social.user.read", "social.agent.read", "social.post.read"]) {
      expect(CapabilityRegistry.isValidId(id)).toBe(true);
      expect(CapabilityRegistry.get(id)?.evidence.length).toBeGreaterThan(0);
    }
  });

  it("authorizes a social read only with the required permission", () => {
    expect(authorize(op(["feed.read"]), "social.post.read", "feed.read").allowed).toBe(true);
    expect(authorize(op(["user.read"]), "social.post.read", "feed.read").allowed).toBe(false);
    expect(authorize(op(["user.read"]), "social.user.read", "user.read").allowed).toBe(true);
  });

  it("capability presence alone does not authorize", () => {
    const d = authorize(op([]), "social.post.read", "feed.read");
    expect(d.allowed).toBe(false);
    expect(d.reasonCode).toBe("denied_permission_missing");
  });

  it("denies an unregistered social capability", () => {
    expect(authorize(op(["feed.read"]), "social.nonexistent.read", "feed.read").reasonCode).toBe("denied_capability_unsupported");
  });
});
