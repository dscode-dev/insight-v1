// CONSOLE-SECURITY-A0 — authorization seam tests.

import { describe, expect, it } from "vitest";

import { authorize } from "@/lib/control-plane/security/authorization";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";
import type { Permission, Role } from "@/types/auth";

function op(permissions: Permission[], roles: Role[] = ["Operations"]): OperatorContext {
  return {
    operatorId: "op-1", operatorDisplayName: "Op", operatorUsername: "op", identityId: "op-1",
    sessionId: "s".repeat(64), roles, permissions, authStrength: null, identityKind: "operator", publicActor: null, delegation: null,
    correlationId: "c", requestId: "r", authenticatedAt: null, source: "insight-console",
  };
}

describe("authorize()", () => {
  it("allows when the operator holds the required permission", () => {
    const d = authorize(op(["feed.hide"]), "social.content.moderate", "feed.hide");
    expect(d.allowed).toBe(true);
    expect(d.reasonCode).toBe("allowed_permission");
    expect(d.policySource).toBe("permission:feed.hide");
  });

  it("denies when the required permission is missing", () => {
    const d = authorize(op(["feed.read"]), "social.content.moderate", "feed.hide");
    expect(d.allowed).toBe(false);
    expect(d.reasonCode).toBe("denied_permission_missing");
  });

  it("allows SuperAdmin via the real role rule (documented policy)", () => {
    const d = authorize(op([], ["SuperAdmin"]), "social.content.moderate", "feed.hide");
    expect(d.allowed).toBe(true);
    expect(d.reasonCode).toBe("allowed_superadmin");
    expect(d.policySource).toBe("role:SuperAdmin");
  });

  it("denies an unsupported capability (registry presence is a precondition, not a grant)", () => {
    const d = authorize(op(["feed.hide"]), "social.nonexistent.moderate", "feed.hide");
    expect(d.allowed).toBe(false);
    expect(d.reasonCode).toBe("denied_capability_unsupported");
  });

  it("fails closed on a mutation with no declared permission policy", () => {
    const d = authorize(op(["feed.hide"]), "social.content.moderate", null);
    expect(d.allowed).toBe(false);
    expect(d.reasonCode).toBe("denied_no_policy");
  });

  it("capability PRESENCE alone does not authorize a registered read capability", () => {
    // atlas.intelligence.read is registered, but the operator lacks the required permission.
    const d = authorize(op(["feed.read"]), "atlas.intelligence.read", "model.read");
    expect(d.allowed).toBe(false);
    expect(d.reasonCode).toBe("denied_permission_missing");
  });
});
