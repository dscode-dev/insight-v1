// CONSOLE-FOUNDATION-A — security boundary tests.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetControlPlaneConfig } from "@/lib/control-plane/config";
import { ServiceRegistry } from "@/lib/control-plane/registries/services";
import { EnvironmentRegistry } from "@/lib/control-plane/registries/environments";
import { CapabilityRegistry } from "@/lib/control-plane/registries/capabilities";
import { PlatformSnapshotService } from "@/lib/control-plane/snapshot";
import { actorFromOperator, rejectClientAssertedActor } from "@/lib/control-plane/actor";

beforeEach(() => {
  process.env.ATLAS_API_BASE_URL = "http://atlas.internal:8085";
  process.env.ATLAS_INTERNAL_TOKEN = "TOP-SECRET-TOKEN";
  process.env.ADMIN_API_INTERNAL_TOKEN = "SERVICE-SECRET";
  __resetControlPlaneConfig();
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const k of ["ATLAS_API_BASE_URL", "ATLAS_INTERNAL_TOKEN", "ADMIN_API_INTERNAL_TOKEN"]) delete process.env[k];
});

describe("no arbitrary host / SSRF", () => {
  it("registry ids are validated and never become URLs", () => {
    expect(ServiceRegistry.isValidId("http://169.254.169.254/latest/meta-data")).toBe(false);
    expect(ServiceRegistry.get("http://evil.example")).toBeNull();
    expect(EnvironmentRegistry.isValidId("file:///etc/passwd")).toBe(false);
    expect(CapabilityRegistry.isValidId("../../secret")).toBe(false);
  });
});

describe("no secret serialization", () => {
  it("public service/environment/capability models omit endpoints + tokens", () => {
    const blob = JSON.stringify({
      services: ServiceRegistry.list(),
      environments: EnvironmentRegistry.list(),
      capabilities: CapabilityRegistry.list(),
    });
    expect(blob).not.toContain("TOP-SECRET-TOKEN");
    expect(blob).not.toContain("SERVICE-SECRET");
    expect(blob).not.toContain("atlas.internal");
    expect(blob).not.toMatch(/:8085|:8090|:8095/);
  });

  it("platform snapshot never serializes tokens or upstream hosts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(JSON.stringify({ status: "healthy" }), { status: 200 }))),
    );
    const snap = await PlatformSnapshotService.generate({ correlationId: null, operatorToken: "op" });
    const blob = JSON.stringify(snap);
    expect(blob).not.toContain("TOP-SECRET-TOKEN");
    expect(blob).not.toContain("atlas.internal");
    expect(blob).not.toContain("http://");
  });
});

describe("actor seam refuses insecure attribution", () => {
  it("never fabricates an operator and reserves publicActor as null", () => {
    const actor = actorFromOperator(
      { id: "op-1", displayName: "Op One", role: "Operations", permissions: [], issuedAt: 0, expiresAt: 0 },
      "corr-1",
    );
    expect(actor.operatorId).toBe("op-1");
    expect(actor.publicActor).toBeNull();
    expect(actor.origin).toBe("insight-console");
  });

  it("hard-rejects client-asserted actor fields", () => {
    expect(() => rejectClientAssertedActor("X-Operator")).toThrow(/forbidden/);
  });
});
