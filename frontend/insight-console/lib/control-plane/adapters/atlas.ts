// Atlas adapter (CONSOLE-FOUNDATION-A). Read-only; Atlas 1.0.0 is FROZEN.
// Consumes existing Atlas contracts only (GET /health). No Atlas modification.

import {
  controlPlaneConfig,
  httpJson,
  mapHealth,
  type AdapterContext,
  type AdapterResult,
  type HealthReadable,
  type HealthReport,
} from "@/lib/control-plane/adapters/base";

export const AtlasAdapter: HealthReadable = {
  serviceId: "atlas",
  environmentId: "robozao",
  async readHealth(ctx: AdapterContext): Promise<AdapterResult<HealthReport>> {
    const cfg = controlPlaneConfig().atlas;
    const res = await httpJson<{ service?: string; status?: string }>({
      service: "atlas",
      environment: "robozao",
      operation: "atlas.health.read",
      baseUrl: cfg.baseUrl,
      path: "/health",
      headers: cfg.token ? { "X-Internal-Token": cfg.token } : {},
      ctx,
    });
    if (!res.ok) return res;
    const status = res.value?.status;
    return {
      ok: true,
      source: res.source,
      value: {
        health: mapHealth(status),
        version: "1.0.0",
        detail: `atlas ${status ?? "unknown"}`,
        activity: {},
      },
    };
  },
};
