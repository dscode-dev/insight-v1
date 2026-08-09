// Node Agent (Robozão) access — THROUGH the Control Plane.
//
// WHAT CHANGED. This module used to hold the Node Agent's address:
//
//     const ROBOZAO_GATEWAY_URL =
//       process.env.ROBOZAO_GATEWAY_URL ?? "http://robozao-gateway:8095";
//
// and call it directly, forwarding the operator's session as a Bearer token.
// Seven API routes used it. insight-context.md v2.0 says "O Console nunca
// acessa diretamente os demais serviços"; this was the last route that did,
// after Fase B moved the other twelve.
//
// The compiled-in default is the part worth remembering. The console container
// holds no service credential, which reads as "it cannot reach anything else" —
// and for the Node Agent that was not true, because the address did not come
// from configuration. Removing the variable from the deployment changed
// nothing at all.
//
// The signatures below are unchanged so the routes that call them did not have
// to move at the same time.
//
// AUTHORITY. The Control Plane authenticates the operator, then presents its
// own service token to the Node Agent along with the operator's name for that
// service's audit log. The console no longer proves anything to anyone.

import { controlPlaneFetch } from "@/lib/control-plane/adapters/console-api";
import { readSessionCookie } from "@/lib/session-cookie";

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
  status:
    | "healthy"
    | "degraded"
    | "unavailable"
    | "unknown"
    | "disabled"
    | "registered";
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
  };
  checked_at: string;
}

export interface RobozaoOperationsAggregate {
  schema_version: "insight.platform.service-registry/1";
  services: RobozaoOperationService[];
  checked_at: string;
}

/**
 * One call to the Node Agent, through the Control Plane.
 *
 * `path` is the Node Agent's own path (`/operations/status`). The Control
 * Plane classifies it against a closed allow-list before forwarding, so an
 * unrecognised path is refused there rather than reaching the agent.
 */
async function nodeAgent(
  path: string,
  init: {
    method?: string;
    body?: unknown;
    idempotencyKey?: string;
    errorPrefix?: string;
  } = {},
): Promise<{ status: number; payload: unknown; replay: boolean }> {
  const token = readSessionCookie();
  if (!token) {
    throw new Error("missing_operator_session");
  }
  const response = await controlPlaneFetch(
    `/node-agent${path.startsWith("/") ? path : `/${path}`}`,
    {
      method: init.method ?? "GET",
      body: init.body,
      token,
      idempotencyKey: init.idempotencyKey,
    },
  );
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${init.errorPrefix ?? "robozao_gateway"}_${response.status}`);
  }
  return {
    status: response.status,
    payload,
    replay: response.headers.get("idempotent-replay") === "true",
  };
}

export async function robozaoStatus(): Promise<RobozaoStatus> {
  const { payload } = await nodeAgent("/vpn/status");
  return payload as RobozaoStatus;
}

/**
 * Operations history reader.
 *
 * The resource allow-list stays here as well as in the Control Plane. It is
 * cheap, it fails before a round trip, and the two lists answer different
 * questions: this one is "does the console have a screen for it", the Control
 * Plane's is "may an operator reach it at all".
 */
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
  const qs = query ? `?${query}` : "";
  const { payload } = await nodeAgent(`/operations/${resource}${qs}`);
  return payload;
}

export async function robozaoOperationCommand(
  body: unknown,
  idempotencyKey: string,
  _correlationId = "",
): Promise<{ status: number; payload: unknown; replay: boolean }> {
  if (!idempotencyKey.trim()) throw new Error("idempotency_key_required");
  return nodeAgent("/operations/commands", {
    method: "POST",
    body,
    idempotencyKey,
    errorPrefix: "robozao_operation",
  });
}

export async function robozaoOperationApprove(
  operationId: string,
): Promise<unknown> {
  // Validated here because it goes into a path. The Control Plane's
  // classifier treats it as an opaque segment, which is the right level
  // there — it must not have to know what a valid operation id looks like.
  if (!/^[a-zA-Z0-9-]+$/.test(operationId)) {
    throw new Error("invalid_operation_id");
  }
  const { payload } = await nodeAgent(
    `/operations/commands/${operationId}/approve`,
    { method: "POST", errorPrefix: "robozao_operation_approve" },
  );
  return payload;
}

export async function robozaoIncidentCommand(
  path: string,
  body: unknown,
): Promise<unknown> {
  if (
    !/^\/operations\/incidents(?:\/[a-zA-Z0-9-]+\/(?:acknowledge|assign|resolve))?$/.test(
      path,
    )
  ) {
    throw new Error("invalid_incident_path");
  }
  const { payload } = await nodeAgent(path, {
    method: "POST",
    body,
    errorPrefix: "robozao_incident",
  });
  return payload;
}

export async function robozaoOperationsStatus(): Promise<RobozaoOperationsAggregate> {
  const { payload } = await nodeAgent("/operations/status");
  return payload as RobozaoOperationsAggregate;
}
