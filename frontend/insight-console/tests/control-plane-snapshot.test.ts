// CONSOLE-FOUNDATION-A — platform snapshot tests (partial state, isolation).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetControlPlaneConfig } from "@/lib/control-plane/config";
import { PlatformSnapshotService } from "@/lib/control-plane/snapshot";

const ctx = { correlationId: "snap-corr", operatorToken: "op-token" };

type Handler = (url: string) => Response | Promise<Response> | never;

function healthy(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

// Factories, NOT constants: a Response body can be consumed only once,
// so a module-level `const Response` is empty for every test after the
// first — which reads as "service unknown" and looks like a topology
// bug rather than a fixture bug.
const cloudOk = () => healthy({
  services: [
    { name: "insight-gateway", status: "up" },
    { name: "insight-social", status: "up" },
    { name: "insight-anvil", status: "up" },
    { name: "postgres", status: "up" },
    { name: "redis", status: "up" },
    { name: "clickhouse", status: "up" },
  ],
});
// What the CONTROL PLANE now returns: the Intelligence plane's health
// plus the Node Agent's report, in one answer. The console no longer
// probes Atlas/Explorer/Nexus itself.
const controlPlaneOk = () => healthy({
  observedAt: new Date().toISOString(),
  services: {
    atlas: { health: "healthy", version: "1.0.0", detail: "atlas healthy", activity: {} },
    explorer: { health: "healthy", version: null, detail: "explorer ok", activity: {} },
    nexus: { health: "healthy", version: null, detail: "nexus ok", activity: {} },
    anvil: { health: "healthy", version: null, detail: "anvil 200", activity: {} },
  },
  nodeAgent: {
    self: { health: "healthy", version: null, detail: "operations status served", activity: {} },
    services: {},
  },
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
  // Matched by HOST, not by path: the Control Plane and the Gateway both
  // serve a "platform/health", and a path-only matcher silently routes
  // one to the other's fixture.
  if (url.includes("control-plane.test")) return controlPlaneOk();
  if (url.includes("gw.test")) return cloudOk();
  return new Response("{}", { status: 200 });
}

beforeEach(() => {
  process.env.CONSOLE_API_BASE_URL = "http://control-plane.test:3002";
  process.env.ADMIN_API_BASE_URL = "http://gw.test/v1";
  process.env.ADMIN_API_INTERNAL_TOKEN = "svc-token";
  __resetControlPlaneConfig();
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const k of ["CONSOLE_API_BASE_URL", "ADMIN_API_BASE_URL", "ADMIN_API_INTERNAL_TOKEN"]) delete process.env[k];
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
      // Matched by HOST: the Control Plane serves a "platform/health"
      // too, and a path match would time BOTH out and destroy the
      // isolation this test exists to prove.
      if (url.includes("gw.test")) throw new DOMException("aborted", "AbortError");
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

  it("one unavailable service ⇒ that service unavailable, others intact", async () => {
    // The console no longer probes Explorer — the Control Plane does,
    // and reports per-service health. So "one service is down" is now
    // expressed in the Control Plane's answer, not by failing a direct
    // call the console never makes.
    install((url) => {
      if (url.includes("control-plane.test")) {
        return healthy({
          observedAt: new Date().toISOString(),
          services: {
            atlas: { health: "healthy", version: "1.0.0", detail: "atlas healthy", activity: {} },
            explorer: { health: "unavailable", version: null, detail: "explorer 503", activity: {} },
            nexus: { health: "healthy", version: null, detail: "nexus ok", activity: {} },
          },
          nodeAgent: {
            self: { health: "healthy", version: null, detail: "served", activity: {} },
            services: {},
          },
        });
      }
      return baseHandler(url);
    });
    const snap = await PlatformSnapshotService.generate(ctx);
    expect(svc(snap.services, "explorer")?.health).toBe("unavailable");
    // Isolation: one bad service does not contaminate the others.
    expect(svc(snap.services, "atlas")?.health).toBe("healthy");
    expect(svc(snap.services, "nexus")?.health).toBe("healthy");
  });

  it("the Control Plane being unreachable does not fabricate health for what is behind it", async () => {
    install((url) => {
      if (url.includes("control-plane.test")) {
        throw new DOMException("aborted", "AbortError");
      }
      return baseHandler(url);
    });
    const snap = await PlatformSnapshotService.generate(ctx);
    // Unknown, NOT unavailable: nobody looked. Reporting them down
    // because the observer is down is how a false incident starts.
    for (const id of ["atlas", "explorer", "nexus"]) {
      expect(svc(snap.services, id)?.health).toBe("unknown");
    }
    // The Product plane is still observable through the Gateway.
    expect(svc(snap.services, "social")?.health).toBe("healthy");
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
