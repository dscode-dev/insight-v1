// Cloud environment service checks.
//
// The Console must not probe platform databases or operational services
// directly. It consumes Gateway-mediated cloud status and Robozao Gateway
// operational status through the unified operations adapters.

import { operationsSnapshot } from "@/lib/operations-adapters";

export type ServiceStatus = "up" | "down" | "degraded";

export interface ServiceHealth {
  name: string;
  kind: "service" | "datastore";
  status: ServiceStatus;
  latency_ms: number | null;
  version: string | null;
  detail: string;
  endpoint: string;
}

export async function cloudServices(): Promise<ServiceHealth[]> {
  const snapshot = await operationsSnapshot();
  return snapshot.domains.google_cloud.map((service) => ({
    name: service.display_name,
    kind: service.service === "databases" ? "datastore" : "service",
    status: toServiceStatus(service.status),
    latency_ms: service.latency_ms,
    version: service.version,
    detail: service.detail,
    endpoint: service.endpoint,
  }));
}

function toServiceStatus(status: string): ServiceStatus {
  if (status === "healthy") return "up";
  if (status === "degraded") return "degraded";
  return "down";
}
