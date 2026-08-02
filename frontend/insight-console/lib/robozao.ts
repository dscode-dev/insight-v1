import { readSessionCookie } from "@/lib/session";

const ROBOZAO_GATEWAY_URL =
  process.env.ROBOZAO_GATEWAY_URL ?? "http://robozao-gateway:8095";

export interface RobozaoServiceStatus {
  service: string;
  endpoint: string;
  status: "healthy" | "degraded" | "unreachable" | "invalid";
  latency_ms: number;
  detail: string;
}

export interface RobozaoStatus {
  vpn_connected: boolean;
  robozao_reachable: boolean;
  operator_validated: boolean;
  services: Record<string, string>;
  registry: RobozaoServiceStatus[];
  checked_at: string;
  source: string;
}

export interface RobozaoOperationService {
  service_id: string;
  endpoint: string;
  transport: "grpc";
  enabled: boolean;
  reachable: boolean;
  latency_ms: number;
  status: "healthy" | "degraded" | "unavailable" | "unknown" | "disabled" | "registered";
  reason?: string;
  identity?: {
    service_id: string;
    service_name: string;
    service_type: string;
    version: string;
    environment?: string;
    tags: string[];
  };
  capabilities?: Array<{
    name: string;
    version: string;
    enabled: boolean;
    description?: string;
  }>;
  metrics?: {
    cpu_percent: number;
    memory_mb: number;
    active_jobs: number;
    uptime_seconds: number;
    counters?: Record<string, number>;
  };
  error?: string;
  checked_at: string;
}

export interface RobozaoOperationsAggregate {
  schema_version: "insight.platform.service-registry/1";
  services: RobozaoOperationService[];
  checked_at: string;
}

export async function robozaoStatus(): Promise<RobozaoStatus> {
  const token = readSessionCookie();
  if (!token) {
    throw new Error("missing_operator_session");
  }
  const res = await fetch(`${ROBOZAO_GATEWAY_URL}/vpn/status`, {
    cache: "no-store",
    signal: AbortSignal.timeout(4000),
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    throw new Error(`robozao_gateway_${res.status}`);
  }
  return (await res.json()) as RobozaoStatus;
}

// ML-C.5e — generic operations-history reader. Forwards the operator session
// token to the Robozão Gateway (operator-authed). `resource` is one of
// events|tickets|runs|datasets|training|history|incidents; `query` is an optional
// URLSearchParams string. Console consumes ONLY the gateway (no direct service).
const OPS_RESOURCES = new Set([
  "events",
  "tickets",
  "runs",
  "datasets",
  "training",
  "history",
  "incidents",
  "actions",
  "commands",
]);

export async function robozaoOps(
  resource: string,
  query = "",
): Promise<unknown> {
  if (!OPS_RESOURCES.has(resource)) {
    throw new Error("unknown_ops_resource");
  }
  const token = readSessionCookie();
  if (!token) {
    throw new Error("missing_operator_session");
  }
  const qs = query ? `?${query}` : "";
  const res = await fetch(`${ROBOZAO_GATEWAY_URL}/operations/${resource}${qs}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`robozao_gateway_${res.status}`);
  }
  return res.json();
}

export async function robozaoOperationCommand(
  body: unknown,
  idempotencyKey: string,
  correlationId = "",
): Promise<{ status: number; payload: unknown; replay: boolean }> {
  const token = readSessionCookie();
  if (!token) throw new Error("missing_operator_session");
  if (!idempotencyKey.trim()) throw new Error("idempotency_key_required");
  const res = await fetch(`${ROBOZAO_GATEWAY_URL}/operations/commands`, {
    method: "POST",
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "Idempotency-Key": idempotencyKey,
      ...(correlationId ? { "X-Correlation-ID": correlationId } : {}),
    },
    body: JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`robozao_operation_${res.status}`);
  return {
    status: res.status,
    payload,
    replay: res.headers.get("idempotent-replay") === "true",
  };
}

export async function robozaoOperationApprove(operationId: string): Promise<unknown> {
  if (!/^[a-zA-Z0-9-]+$/.test(operationId)) throw new Error("invalid_operation_id");
  const token = readSessionCookie();
  if (!token) throw new Error("missing_operator_session");
  const res = await fetch(
    `${ROBOZAO_GATEWAY_URL}/operations/commands/${operationId}/approve`,
    {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
      headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
    },
  );
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`robozao_operation_approve_${res.status}`);
  return payload;
}

export async function robozaoIncidentCommand(
  path: string,
  body: unknown,
): Promise<unknown> {
  if (!/^\/operations\/incidents(?:\/[a-zA-Z0-9-]+\/(?:acknowledge|assign|resolve))?$/.test(path)) {
    throw new Error("invalid_incident_path");
  }
  const token = readSessionCookie();
  if (!token) throw new Error("missing_operator_session");
  const res = await fetch(`${ROBOZAO_GATEWAY_URL}${path}`, {
    method: "POST",
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(`robozao_incident_${res.status}`);
  }
  return payload;
}

export async function robozaoOperationsStatus(): Promise<RobozaoOperationsAggregate> {
  const token = readSessionCookie();
  if (!token) {
    throw new Error("missing_operator_session");
  }
  const res = await fetch(`${ROBOZAO_GATEWAY_URL}/operations/status`, {
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    throw new Error(`robozao_gateway_${res.status}`);
  }
  return (await res.json()) as RobozaoOperationsAggregate;
}
