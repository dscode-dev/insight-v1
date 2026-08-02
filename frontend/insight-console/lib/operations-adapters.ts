// Operations snapshot — LEGACY-SHAPE COMPATIBILITY LAYER (CONSOLE-FOUNDATION-A).
//
// Migration note: the hardcoded topology maps (CLOUD_META / SERVICE_META) and the
// per-domain probe functions that used to live here were REMOVED. Platform truth
// is now assembled server-side by the Control Plane (registries + typed adapters
// + PlatformSnapshotService). This module only MAPS the canonical
// `PlatformSnapshot` into the legacy `OperationsSnapshot` shape the existing
// Operations Center still renders — so the UI keeps working while consuming
// registry/snapshot truth instead of frontend-baked topology.
//
// The `endpoint` field intentionally carries the ENVIRONMENT LABEL, never an
// internal URL: the browser must not learn upstream hosts.

import { readSessionCookie } from "@/lib/session";
import { PlatformSnapshotService } from "@/lib/control-plane";
import type {
  AdapterKind,
  PlatformSnapshot,
  ServiceSnapshot,
  SourceStatus,
} from "@/lib/control-plane/types";

export type OperationsDomain = "google_cloud" | "robozao";
export type OperationsStatus = "healthy" | "degraded" | "unavailable" | "unknown";

export interface ServiceAdapterSnapshot {
  domain: OperationsDomain;
  service: string;
  display_name: string;
  environment: string;
  host: string;
  region: string;
  infrastructure: string;
  runtime: string;
  api_style: string;
  preferred_transport: "grpc" | "http" | "gateway";
  status: OperationsStatus;
  health: OperationsStatus;
  operational_state: string;
  current_activity: Record<string, string | number | null>;
  dependencies: string[];
  health_endpoint: string;
  metrics_endpoint: string | null;
  last_heartbeat: string | null;
  running_since: string | null;
  restart_count: number | null;
  metrics: {
    cpu_percent?: number;
    memory_mb?: number;
    latency_ms?: number | null;
    active_jobs?: number;
    error_count?: number;
  };
  metrics_summary: string;
  version: string | null;
  capabilities: string[];
  endpoint: string;
  detail: string;
  latency_ms: number | null;
}

export interface OperationsSnapshot {
  domains: {
    google_cloud: ServiceAdapterSnapshot[];
    robozao: ServiceAdapterSnapshot[];
  };
  checked_at: string;
  /** Additive (CONSOLE-FOUNDATION-A): honest partial-state markers. */
  partial?: boolean;
  sources?: SourceStatus[];
}

function transportOf(protocol: ServiceSnapshot["service"]["protocol"]): ServiceAdapterSnapshot["preferred_transport"] {
  if (protocol === "grpc") return "grpc";
  if (protocol === "gateway") return "gateway";
  return "http";
}

function apiStyleOf(kind: AdapterKind): string {
  switch (kind) {
    case "atlas": return "Atlas internal API";
    case "explorer": return "Explorer API";
    case "gateway": return "Gateway platform-health";
    case "robozao": return "Unified Operations Protocol";
    case "nexus": return "Nexus authed API";
    default: return "not directly observed";
  }
}

function toRow(s: ServiceSnapshot): ServiceAdapterSnapshot {
  const isCloud = s.service.environmentId === "google-cloud";
  const status = s.health as OperationsStatus;
  const metrics: ServiceAdapterSnapshot["metrics"] = { latency_ms: s.source.latencyMs };
  const a = s.activity;
  if (typeof a["cpu_percent"] === "number") metrics.cpu_percent = a["cpu_percent"];
  if (typeof a["memory_mb"] === "number") metrics.memory_mb = a["memory_mb"];
  if (typeof a["active_jobs"] === "number") metrics.active_jobs = a["active_jobs"];
  if (s.source.error) metrics.error_count = 1;
  return {
    domain: isCloud ? "google_cloud" : "robozao",
    service: s.service.id,
    display_name: s.service.displayName,
    environment: "production",
    host: isCloud ? "google-cloud" : "robozao",
    region: isCloud ? "cloud" : "on-prem",
    infrastructure: isCloud ? "Google Cloud" : "Robozão Docker Compose",
    runtime: s.service.serviceType,
    api_style: apiStyleOf(s.service.adapterKind),
    preferred_transport: transportOf(s.service.protocol),
    status,
    health: status,
    operational_state: s.detail,
    current_activity: { operation: s.detail, ...a },
    dependencies: s.service.dependencies,
    health_endpoint: "control-plane adapter",
    metrics_endpoint: null,
    last_heartbeat: s.source.observedAt,
    running_since: null,
    restart_count: null,
    metrics,
    metrics_summary: s.source.error ? s.source.error.message : s.detail,
    version: s.version,
    capabilities: s.service.capabilities,
    // Environment label only — NEVER an internal URL.
    endpoint: s.service.environmentId,
    detail: s.detail,
    latency_ms: s.source.latencyMs,
  };
}

function fromSnapshot(snapshot: PlatformSnapshot): OperationsSnapshot {
  const google_cloud: ServiceAdapterSnapshot[] = [];
  const robozao: ServiceAdapterSnapshot[] = [];
  for (const s of snapshot.services) {
    (s.service.environmentId === "google-cloud" ? google_cloud : robozao).push(toRow(s));
  }
  return {
    domains: { google_cloud, robozao },
    checked_at: snapshot.generatedAt,
    partial: snapshot.partial,
    sources: snapshot.sources,
  };
}

/**
 * Legacy Operations Center data source, now backed by the Control Plane.
 * Assembles the snapshot server-side and maps it to the historical shape.
 */
export async function operationsSnapshot(): Promise<OperationsSnapshot> {
  const snapshot = await PlatformSnapshotService.generate({
    correlationId: null,
    operatorToken: readSessionCookie(),
  });
  return fromSnapshot(snapshot);
}
