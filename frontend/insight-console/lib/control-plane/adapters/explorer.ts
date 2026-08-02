// Explorer adapter (CONSOLE-FOUNDATION-A). Read-only. Consumes Explorer's
// existing health contract; intelligence/collection logic is untouched.

import {
  controlPlaneConfig,
  httpJson,
  mapHealth,
  type AdapterContext,
  type AdapterResult,
  type HealthReadable,
  type HealthReport,
} from "@/lib/control-plane/adapters/base";

export const ExplorerAdapter: HealthReadable = {
  serviceId: "explorer",
  environmentId: "robozao",
  async readHealth(ctx: AdapterContext): Promise<AdapterResult<HealthReport>> {
    const cfg = controlPlaneConfig().explorer;
    const res = await httpJson<{ status?: string; version?: string; active_jobs?: number }>({
      service: "explorer",
      environment: "robozao",
      operation: "explorer.health.read",
      baseUrl: cfg.baseUrl,
      path: "/health",
      ctx,
    });
    if (!res.ok) return res;
    const body = res.value ?? {};
    return {
      ok: true,
      source: res.source,
      value: {
        health: mapHealth(body.status),
        version: typeof body.version === "string" ? body.version : null,
        detail: `explorer ${body.status ?? "unknown"}`,
        activity:
          typeof body.active_jobs === "number" ? { active_jobs: body.active_jobs } : {},
      },
    };
  },
};
