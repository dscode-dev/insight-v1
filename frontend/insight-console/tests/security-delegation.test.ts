// CONSOLE-SECURITY-A0 — delegation foundation tests (no activation).

import { describe, expect, it } from "vitest";

import {
  resolveDelegation,
  rejectSelfDelegation,
  assertOperatorPreserved,
  type DelegationContext,
} from "@/lib/control-plane/security/delegation";

describe("delegation foundation", () => {
  it("has NO active delegation by default", () => {
    expect(resolveDelegation()).toBeNull();
  });

  it("rejects arbitrary browser self-delegation (act_as_user_id)", () => {
    expect(() => rejectSelfDelegation("act_as_user_id")).toThrow(/self-delegation is forbidden/);
  });

  it("enforces that the original operator is preserved (never replaced)", () => {
    const good: DelegationContext = {
      delegationId: "d1", operatorId: "op-1", subjectType: "official_identity", subjectId: "ninja",
      mode: "act_as_identity", scope: ["publish"], reason: "official post", issuedAt: "t",
      expiresAt: null, revokedAt: null,
    };
    expect(() => assertOperatorPreserved(good, "op-1")).not.toThrow();

    // operator dropped
    const dropped = { ...good, operatorId: "" };
    expect(() => assertOperatorPreserved(dropped, "op-1")).toThrow(/drops the operator/);

    // delegated identity trying to replace a different operator (impersonation)
    expect(() => assertOperatorPreserved(good, "op-2")).toThrow(/does not match/);
  });
});
