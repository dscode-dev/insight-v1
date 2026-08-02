// Typed adapter foundation (CONSOLE-FOUNDATION-A, Stage 4/5). SERVER-ONLY.
//
// Shared transport for service adapters: bounded timeout, cancellation,
// response-size sanity, canonical error normalization, and per-source
// attribution. Adapters inject their own auth headers (tokens read from
// server config, NEVER serialized). This is NOT a generic proxy — every call
// targets a fixed, registry/config-resolved upstream; the browser can never
// choose a host or path (Stage 11).

import { controlPlaneConfig } from "@/lib/control-plane/config";
import {
  ControlPlaneError,
  codeFromUpstreamStatus,
  normalizeThrown,
  sourceStateForCode,
} from "@/lib/control-plane/errors";
import { observe } from "@/lib/control-plane/observability";
import type { EnvironmentId, HealthState, SourceStatus } from "@/lib/control-plane/types";

const DEFAULT_TIMEOUT_MS = 5000;
const MAX_RESPONSE_BYTES = 2_000_000; // 2 MB sanity cap

export interface AdapterContext {
  readonly correlationId: string | null;
  /** Verified operator session token, forwarded server-side where required. */
  readonly operatorToken?: string | null;
  readonly timeoutMs?: number;
}

export interface HealthReport {
  readonly health: HealthState;
  readonly version: string | null;
  readonly detail: string;
  readonly activity: Record<string, string | number | null>;
}

export type AdapterResult<T> =
  | { readonly ok: true; readonly value: T; readonly source: SourceStatus }
  | { readonly ok: false; readonly error: ControlPlaneError; readonly source: SourceStatus };

/** Small capability-oriented interfaces — Atlas is not Social is not Anvil. */
export interface HealthReadable {
  readonly serviceId: string;
  readonly environmentId: EnvironmentId;
  readHealth(ctx: AdapterContext): Promise<AdapterResult<HealthReport>>;
}

export function mapHealth(raw: string | undefined | null): HealthState {
  const v = String(raw ?? "").toLowerCase();
  if (v === "up" || v === "healthy" || v === "ok" || v === "ready") return "healthy";
  if (v === "degraded") return "degraded";
  if (v === "down" || v === "unhealthy" || v === "unavailable" || v === "unreachable")
    return "unavailable";
  return "unknown";
}

function nowIso(): string {
  return new Date().toISOString();
}

function okSource(
  service: string,
  environment: EnvironmentId,
  latencyMs: number,
  degraded = false,
): SourceStatus {
  return {
    service,
    environment,
    state: degraded ? "degraded" : "available",
    observedAt: nowIso(),
    latencyMs,
    stale: false,
  };
}

function errSource(service: string, environment: EnvironmentId, err: ControlPlaneError, latencyMs: number): SourceStatus {
  return {
    service,
    environment,
    state: sourceStateForCode(err.code),
    observedAt: nowIso(),
    latencyMs,
    stale: false,
    error: { code: err.code, retryable: err.retryable, message: err.message },
  };
}

export interface HttpJsonArgs {
  service: string;
  environment: EnvironmentId;
  operation: string;
  baseUrl: string; // resolved from config; never browser-supplied
  path: string; // fixed path; never browser-supplied
  headers?: Record<string, string>;
  method?: "GET" | "POST";
  body?: unknown;
  ctx: AdapterContext;
}

/**
 * Perform one server-side upstream JSON call with full normalization.
 * Returns a discriminated AdapterResult carrying source attribution either way.
 */
export async function httpJson<T = unknown>(args: HttpJsonArgs): Promise<AdapterResult<T>> {
  const { service, environment, operation, baseUrl, path, ctx } = args;
  const timeoutMs = ctx.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const correlationId = ctx.correlationId ?? undefined;
  const started = Date.now();

  if (!baseUrl) {
    const err = new ControlPlaneError("CONFIGURATION_ERROR", `${service} not configured`, {
      service, environment, operation, correlationId,
    });
    observe("adapter_request_failed", { service, environment, operation, code: err.code, correlationId });
    return { ok: false, error: err, source: errSource(service, environment, err, 0) };
  }

  observe("adapter_request_started", { service, environment, operation, correlationId });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${baseUrl}${path}`, {
      method: args.method ?? "GET",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(args.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(correlationId ? { "X-Request-Id": correlationId } : {}),
        ...(args.headers ?? {}),
      },
      body: args.body !== undefined ? JSON.stringify(args.body) : undefined,
    });
    const latency = Date.now() - started;

    if (!res.ok) {
      const err = new ControlPlaneError(codeFromUpstreamStatus(res.status), `upstream HTTP ${res.status}`, {
        service, environment, operation, correlationId,
      });
      observe("adapter_request_failed", { service, environment, operation, code: err.code, latencyMs: latency, correlationId });
      return { ok: false, error: err, source: errSource(service, environment, err, latency) };
    }

    const text = await res.text();
    if (text.length > MAX_RESPONSE_BYTES) {
      const err = new ControlPlaneError("INVALID_RESPONSE", "upstream response too large", {
        service, environment, operation, correlationId,
      });
      return { ok: false, error: err, source: errSource(service, environment, err, latency) };
    }
    let parsed: unknown;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      const err = new ControlPlaneError("INVALID_RESPONSE", "upstream returned invalid JSON", {
        service, environment, operation, correlationId,
      });
      observe("adapter_request_failed", { service, environment, operation, code: err.code, latencyMs: latency, correlationId });
      return { ok: false, error: err, source: errSource(service, environment, err, latency) };
    }
    observe("adapter_request_completed", { service, environment, operation, latencyMs: latency, correlationId });
    return { ok: true, value: parsed as T, source: okSource(service, environment, latency) };
  } catch (thrown) {
    const latency = Date.now() - started;
    const err = normalizeThrown(thrown, { service, environment, operation, correlationId });
    const evt = err.code === "TIMEOUT" ? "adapter_request_timeout" : "adapter_request_failed";
    observe(evt, { service, environment, operation, code: err.code, latencyMs: latency, correlationId });
    return { ok: false, error: err, source: errSource(service, environment, err, latency) };
  } finally {
    clearTimeout(timer);
  }
}

/** Convenience: resolved upstream config for the adapters. */
export { controlPlaneConfig };
