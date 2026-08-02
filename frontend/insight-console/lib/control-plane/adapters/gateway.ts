// Cloud Gateway adapter (CONSOLE-FOUNDATION-A). Read-only.
//
// Consumes the gateway's real platform-health endpoint (the gateway performs the
// true PG/Redis/ClickHouse/social/anvil probes — the Console never probes DBs).
// Auth: service token (X-Console-Service-Token, from server config) + the
// verified operator session Bearer (forwarded server-side). Returns per-service
// health for the cloud environment plus the gateway's own state.

import {
  controlPlaneConfig,
  httpJson,
  mapHealth,
  type AdapterContext,
  type AdapterResult,
  type HealthReport,
} from "@/lib/control-plane/adapters/base";

export interface CloudHealth {
  readonly self: HealthReport; // the gateway itself
  readonly services: Record<string, HealthReport>; // keyed by registry service id
}

interface PlatformHealthRow {
  name?: string;
  status?: string;
  latency_ms?: number | null;
  version?: string | null;
  error?: string | null;
  last_checked_at?: string;
}

// platform-health service name → registry service id (no invention).
const NAME_TO_ID: Record<string, string> = {
  "insight-gateway": "gateway",
  gateway: "gateway",
  "insight-social": "social",
  social: "social",
  "insight-anvil": "anvil",
  anvil: "anvil",
  postgres: "cloud-postgres",
  redis: "cloud-redis",
  clickhouse: "cloud-clickhouse",
};

function platformHealthPath(baseUrl: string): string {
  return baseUrl.endsWith("/v1")
    ? "/console/platform/health"
    : "/v1/console/platform/health";
}

export const GatewayAdapter = {
  serviceId: "gateway" as const,
  environmentId: "google-cloud" as const,

  async readCloud(ctx: AdapterContext): Promise<AdapterResult<CloudHealth>> {
    const cfg = controlPlaneConfig().gateway;
    const headers: Record<string, string> = {};
    if (cfg.token) headers["X-Console-Service-Token"] = cfg.token;
    if (ctx.operatorToken) headers["Authorization"] = `Bearer ${ctx.operatorToken}`;

    const res = await httpJson<{ services?: PlatformHealthRow[] }>({
      service: "gateway",
      environment: "google-cloud",
      operation: "gateway.platform_health.read",
      baseUrl: cfg.baseUrl,
      path: platformHealthPath(cfg.baseUrl),
      headers,
      ctx,
    });
    if (!res.ok) return res;

    const rows = Array.isArray(res.value?.services) ? res.value!.services : [];
    const services: Record<string, HealthReport> = {};
    for (const row of rows) {
      const id = row.name ? NAME_TO_ID[row.name] : undefined;
      if (!id) continue;
      services[id] = {
        health: mapHealth(row.status),
        version: typeof row.version === "string" ? row.version : null,
        detail: row.error ? row.error : `${row.status ?? "unknown"}`,
        activity:
          typeof row.latency_ms === "number" ? { latency_ms: row.latency_ms } : {},
      };
    }
    // The gateway answered platform-health ⇒ it is itself serving.
    const self: HealthReport =
      services["gateway"] ?? {
        health: "healthy",
        version: process.env.CLOUD_GATEWAY_VERSION ?? null,
        detail: "platform-health served",
        activity: {},
      };
    return { ok: true, source: res.source, value: { self, services } };
  },
};
