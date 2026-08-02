// CONSOLE-FOUNDATION-A — platform snapshot tests (partial state, isolation).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetControlPlaneConfig } from "@/lib/control-plane/config";
import { PlatformSnapshotService } from "@/lib/control-plane/snapshot";

const ctx = { correlationId: "snap-corr", operatorToken: "op-token" };

type Handler = (url: string) => Response | Promise<Response> | never;

function healthy(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

const CLOUD_OK = healthy({
  services: [
    { name: "insight-gateway", status: "up" },
    { name: "insight-social", status: "up" },
    { name: "insight-anvil", status: "up" },
    { name: "postgres", status: "up" },
    { name: "redis", status: "up" },
    { name: "clickhouse", status: "up" },
  ],
});
const ROBO_OK = healthy({
  services: [
    { service_id: "insight-explorer", status: "healthy" },
    { identity: { service_id: "insight-atlas" }, status: "healthy" },
  ],
});

function install(handler: Handler) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: unknown) => {
      const url = String(input);
      return Promise.resolve(handler(url));
    }),
  );
}

function baseHandler(url: string): Response {
  if (url.includes("atlas.test") && url.includes("/health")) return healthy({ service: "atlas", status: "healthy" });
  if (url.includes("explorer.test")) return healthy({ status: "healthy", version: "0.0.20" });
  if (url.includes("nexus.test")) return healthy({ status: "ok" });
  if (url.includes("platform/health")) return CLOUD_OK;
  if (url.includes("operations/status")) return ROBO_OK;
  return new Response("{}", { status: 200 });
}

beforeEach(() => {
  process.env.ATLAS_API_BASE_URL = "http://atlas.test:8085";
  process.env.EXPLORER_API_BASE_URL = "http://explorer.test:8090";
  process.env.ROBOZAO_GATEWAY_URL = "http://robo.test:8095";
  process.env.NEXUS_API_BASE_URL = "http://nexus.test:8090";
  process.env.ADMIN_API_BASE_URL = "http://gw.test/v1";
  process.env.ADMIN_API_INTERNAL_TOKEN = "svc-token";
  __resetControlPlaneConfig();
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const k of ["ATLAS_API_BASE_URL", "EXPLORER_API_BASE_URL", "ROBOZAO_GATEWAY_URL", "NEXUS_API_BASE_URL", "ADMIN_API_BASE_URL", "ADMIN_API_INTERNAL_TOKEN"]) delete process.env[k];
});

function svc(snapshotServices: { service: { id: string }; health: string }[], id: string) {
  return snapshotServices.find((s) => s.service.id === id);
}

describe("PlatformSnapshotService", () => {
  it("all sources available ⇒ not partial, real health, no fake health for unprobed services", async () => {
    install(baseHandler);
    const snap = await PlatformSnapshotService.generate(ctx);
    expect(snap.partial).toBe(false);
    expect(snap.environments).toHaveLength(2);
    expect(snap.services).toHaveLength(16);
    expect(svc(snap.services, "atlas")?.health).toBe("healthy");
    expect(svc(snap.services, "social")?.health).toBe("healthy");
    // Unprobed service is honestly unknown, never healthy.
    expect(svc(snap.services, "sport-hub")?.health).toBe("unknown");
    expect(snap.capabilities.byState.AVAILABLE).toBeGreaterThan(0);
  });

  it("isolates one timeout: gateway down ⇒ partial, dependents unknown, atlas still healthy", async () => {
    install((url) => {
      if (url.includes("platform/health")) throw new DOMException("aborted", "AbortError");
      return baseHandler(url);
    });
    const snap = await PlatformSnapshotService.generate(ctx);
    expect(snap.partial).toBe(true);
    expect(svc(snap.services, "gateway")?.health).toBe("unavailable");
    expect(svc(snap.services, "social")?.health).toBe("unknown"); // not fabricated down
    expect(svc(snap.services, "atlas")?.health).toBe("healthy"); // isolation
    const cloudSource = snap.sources.find((s) => s.service === "gateway");
    expect(cloudSource?.state).toBe("timeout");
  });

  it("one unavailable service ⇒ partial, that service unavailable, others intact", async () => {
    install((url) => {
      if (url.includes("explorer.test")) return new Response("no", { status: 503 });
      return baseHandler(url);
    });
    const snap = await PlatformSnapshotService.generate(ctx);
    expect(snap.partial).toBe(true);
    expect(svc(snap.services, "explorer")?.health).toBe("unavailable");
    expect(svc(snap.services, "atlas")?.health).toBe("healthy");
  });

  it("aggregation is deterministic in shape", async () => {
    install(baseHandler);
    const a = await PlatformSnapshotService.generate(ctx);
    const b = await PlatformSnapshotService.generate(ctx);
    expect(a.services.length).toBe(b.services.length);
    expect(a.environments.length).toBe(b.environments.length);
    expect(a.capabilities.total).toBe(b.capabilities.total);
    expect(a.services.map((s) => s.service.id)).toEqual(b.services.map((s) => s.service.id));
  });
});
