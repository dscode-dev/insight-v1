// Robozão Gateway adapter (CONSOLE-FOUNDATION-A). Read-only.
//
// Consumes the Unified Operations Protocol (GET /operations/status) — an
// operator-authed aggregate of the on-prem services. Auth: verified operator
// session Bearer (forwarded server-side). Returns per-service health plus the
// robozão-gateway's own state.

import {
  controlPlaneConfig,
  httpJson,
  mapHealth,
  type AdapterContext,
  type AdapterResult,
  type HealthReport,
} from "@/lib/control-plane/adapters/base";
import { ServiceRegistry } from "@/lib/control-plane/registries/services";

export interface RobozaoHealth {
  readonly self: HealthReport;
  readonly services: Record<string, HealthReport>; // keyed by registry service id
}

interface OpsService {
  service_id?: string;
  status?: string;
  latency_ms?: number;
  identity?: { service_id?: string; version?: string };
  metrics?: { active_jobs?: number; cpu_percent?: number; memory_mb?: number };
  error?: string;
}

export const RobozaoAdapter = {
  serviceId: "robozao-gateway" as const,
  environmentId: "robozao" as const,

  async readOperations(ctx: AdapterContext): Promise<AdapterResult<RobozaoHealth>> {
    const cfg = controlPlaneConfig().robozaoGateway;
    const headers: Record<string, string> = {};
    if (ctx.operatorToken) headers["Authorization"] = `Bearer ${ctx.operatorToken}`;

    const res = await httpJson<{ services?: OpsService[] }>({
      service: "robozao-gateway",
      environment: "robozao",
      operation: "robozao.operations.read",
      baseUrl: cfg.baseUrl,
      path: "/operations/status",
      headers,
      ctx,
    });
    if (!res.ok) return res;

    const rows = Array.isArray(res.value?.services) ? res.value!.services : [];
    const services: Record<string, HealthReport> = {};
    for (const row of rows) {
      const rawId = row.identity?.service_id ?? row.service_id;
      // The Operations protocol now emits canonical registry IDs. Unknown or
      // legacy aliases are rejected rather than translated by another topology
      // map in the Console.
      const id = rawId && ServiceRegistry.isValidId(rawId) ? rawId : undefined;
      if (!id) continue;
      const activity: Record<string, string | number | null> = {};
      if (typeof row.metrics?.active_jobs === "number") activity["active_jobs"] = row.metrics.active_jobs;
      if (typeof row.metrics?.cpu_percent === "number") activity["cpu_percent"] = row.metrics.cpu_percent;
      services[id] = {
        health: mapHealth(row.status),
        version: typeof row.identity?.version === "string" ? row.identity.version : null,
        detail: row.error ? row.error : `${row.status ?? "unknown"}`,
        activity,
      };
    }
    const self: HealthReport = {
      health: "healthy",
      version: null,
      detail: "operations status served",
      activity: {},
    };
    return { ok: true, source: res.source, value: { self, services } };
  },
};
