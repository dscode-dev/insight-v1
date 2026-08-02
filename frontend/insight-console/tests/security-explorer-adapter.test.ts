// CONSOLE-SECURITY-A1 — Explorer privileged adapter (Stage 10) attribution test.

import { afterEach, describe, expect, it, vi } from "vitest";

// Mock the underlying Explorer client so we can inspect the attribution passed.
vi.mock("@/lib/data-intelligence", () => ({
  explorerCall: vi.fn(async () => new Response("{}", { status: 200 })),
}));

import { explorerCall } from "@/lib/data-intelligence";
import { explorerPrivilegedCall } from "@/lib/control-plane/adapters/explorer-privileged";
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
  it("derives X-Operator attribution server-side (username) + propagates correlation", async () => {
    await explorerPrivilegedCall(op(), "missions", "POST", { a: 1 });
    expect(explorerCall).toHaveBeenCalledWith("missions", "POST", { a: 1 }, "darlan", "corr-77");
  });

  it("falls back to operator id when username is absent (still server-derived)", async () => {
    await explorerPrivilegedCall(op({ operatorUsername: null }), "jobs", "GET", undefined);
    expect(explorerCall).toHaveBeenCalledWith("jobs", "GET", undefined, "op-uuid", "corr-77");
  });

  it("the attribution comes ONLY from OperatorContext — there is no browser input to it", async () => {
    // The adapter signature accepts no client-controlled actor; the only actor
    // source is the verified OperatorContext.
    await explorerPrivilegedCall(op({ operatorUsername: "verified" }), "sources", "GET", undefined);
    const call = vi.mocked(explorerCall).mock.calls[0]!;
    expect(call[3]).toBe("verified");
  });
});
