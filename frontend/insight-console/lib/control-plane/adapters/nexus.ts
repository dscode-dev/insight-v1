// Nexus adapter (CONSOLE-FOUNDATION-A). Read-only health.
//
// Nexus has no Console-side URL configured by default. When NEXUS_API_BASE_URL
// is unset, httpJson returns CONFIGURATION_ERROR and the snapshot reports Nexus
// as configured=false / unknown — an HONEST "we can't reach it", never a fake
// healthy or a guessed production host.

import {
  controlPlaneConfig,
  httpJson,
  mapHealth,
  type AdapterContext,
  type AdapterResult,
  type HealthReadable,
  type HealthReport,
} from "@/lib/control-plane/adapters/base";

export const NexusAdapter: HealthReadable = {
  serviceId: "nexus",
  environmentId: "robozao",
  async readHealth(ctx: AdapterContext): Promise<AdapterResult<HealthReport>> {
    const cfg = controlPlaneConfig().nexus;
    const res = await httpJson<{ status?: string; version?: string }>({
      service: "nexus",
      environment: "robozao",
      operation: "nexus.health.read",
      baseUrl: cfg.baseUrl,
      path: "/healthz",
      ctx,
    });
    if (!res.ok) return res;
    const body = res.value ?? {};
    return {
      ok: true,
      source: res.source,
      value: {
        health: mapHealth(body.status ?? "ok"),
        version: typeof body.version === "string" ? body.version : null,
        detail: `nexus ${body.status ?? "reachable"}`,
        activity: {},
      },
    };
  },
};
