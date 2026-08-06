// Explorer privileged adapter — attribution and telemetry.
//
// This used to assert that the console derived `X-Operator` server-side
// and passed it down. It no longer passes an actor AT ALL: the Insight
// Control Plane resolves the operator from the session it already
// verified and forwards it to Explorer itself.
//
// That is a stronger guarantee than sending a trustworthy value —
// there is no actor field on this path for anything to influence — so
// the test now pins the absence rather than the value.

import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/data-intelligence", () => ({
  explorerCall: vi.fn(async () => new Response("{}", { status: 200 })),
}));
vi.mock("@/lib/control-plane/security/observability", () => ({
  observeSecurity: vi.fn(),
}));

import { explorerCall } from "@/lib/data-intelligence";
import { explorerPrivilegedCall } from "@/lib/control-plane/adapters/explorer-privileged";
import { observeSecurity } from "@/lib/control-plane/security/observability";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";

function op(overrides: Partial<OperatorContext> = {}): OperatorContext {
  return {
    operatorId: "op-uuid", operatorDisplayName: "Op", operatorUsername: "darlan", identityId: "op-uuid",
    sessionId: "s".repeat(64), roles: ["Operations"], permissions: [], authStrength: null,
    identityKind: "operator", publicActor: null,
    delegation: null, correlationId: "corr-77", requestId: "req-1", authenticatedAt: null, source: "insight-console",
    ...overrides,
  };
}

afterEach(() => vi.clearAllMocks());

describe("explorerPrivilegedCall", () => {
  it("forwards only path, method and body — no actor travels from the console", async () => {
    await explorerPrivilegedCall(op(), "missions", "POST", { a: 1 });
    expect(explorerCall).toHaveBeenCalledWith("missions", "POST", { a: 1 });
  });

  it("passes no operator identity in any argument", async () => {
    // The whole point: with no actor argument there is nothing for a
    // caller — or a future refactor — to populate from browser input.
    await explorerPrivilegedCall(op({ operatorUsername: "verified" }), "sources", "GET", undefined);
    const call = vi.mocked(explorerCall).mock.calls[0]!;
    expect(call).toHaveLength(3);
    expect(JSON.stringify(call)).not.toContain("verified");
    expect(JSON.stringify(call)).not.toContain("op-uuid");
  });

  it("still emits security telemetry for the privileged flow", async () => {
    await explorerPrivilegedCall(op(), "jobs", "GET", undefined);
    expect(observeSecurity).toHaveBeenCalledWith(
      "privileged_adapter_request",
      expect.objectContaining({ operatorId: "op-uuid", service: "explorer" }),
    );
  });

  it("reports a failure through telemetry and rethrows", async () => {
    vi.mocked(explorerCall).mockRejectedValueOnce(new Error("explorer down"));
    await expect(
      explorerPrivilegedCall(op(), "jobs", "GET", undefined),
    ).rejects.toThrow("explorer down");
    expect(observeSecurity).toHaveBeenCalledWith(
      "privileged_adapter_failure",
      expect.objectContaining({ service: "explorer" }),
    );
  });
});
