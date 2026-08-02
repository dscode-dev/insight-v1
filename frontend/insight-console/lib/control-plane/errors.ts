// Canonical Control Plane error model (CONSOLE-FOUNDATION-A, Stage 5).
//
// The browser must distinguish real failure modes (the audit found these
// conflated). Errors never leak secrets, stack traces, or internal URLs — only
// a safe code + message. HTTP status is chosen from the code; upstream failures
// are NOT flattened to 200.

import type { EnvironmentId, SourceState } from "@/lib/control-plane/types";

export type ControlPlaneErrorCode =
  | "CONFIGURATION_ERROR"
  | "SERVICE_UNAVAILABLE"
  | "TIMEOUT"
  | "UNAUTHORIZED"
  | "FORBIDDEN"
  | "UPSTREAM_ERROR"
  | "INVALID_RESPONSE"
  | "CAPABILITY_UNSUPPORTED"
  | "CAPABILITY_UNAVAILABLE"
  | "NOT_FOUND"
  | "BAD_REQUEST"
  | "CONFLICT"
  | "PARTIAL_DATA";

export interface ControlPlaneErrorShape {
  readonly code: ControlPlaneErrorCode;
  readonly service?: string;
  readonly environment?: EnvironmentId;
  readonly operation?: string;
  readonly retryable: boolean;
  readonly timestamp: string;
  readonly correlationId?: string;
  /** Safe, non-sensitive human message. */
  readonly message: string;
}

const RETRYABLE: ReadonlySet<ControlPlaneErrorCode> = new Set([
  "SERVICE_UNAVAILABLE",
  "TIMEOUT",
  "UPSTREAM_ERROR",
  "PARTIAL_DATA",
]);

const HTTP_STATUS: Record<ControlPlaneErrorCode, number> = {
  CONFIGURATION_ERROR: 503,
  SERVICE_UNAVAILABLE: 503,
  TIMEOUT: 504,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  UPSTREAM_ERROR: 502,
  INVALID_RESPONSE: 502,
  CAPABILITY_UNSUPPORTED: 501,
  CAPABILITY_UNAVAILABLE: 503,
  NOT_FOUND: 404,
  BAD_REQUEST: 400,
  CONFLICT: 409,
  PARTIAL_DATA: 200,
};

export class ControlPlaneError extends Error {
  readonly code: ControlPlaneErrorCode;
  readonly service?: string;
  readonly environment?: EnvironmentId;
  readonly operation?: string;
  readonly correlationId?: string;

  constructor(
    code: ControlPlaneErrorCode,
    message: string,
    ctx: {
      service?: string;
      environment?: EnvironmentId;
      operation?: string;
      correlationId?: string;
    } = {},
  ) {
    super(message);
    this.name = "ControlPlaneError";
    this.code = code;
    this.service = ctx.service;
    this.environment = ctx.environment;
    this.operation = ctx.operation;
    this.correlationId = ctx.correlationId;
  }

  get retryable(): boolean {
    return RETRYABLE.has(this.code);
  }

  get httpStatus(): number {
    return HTTP_STATUS[this.code];
  }

  toShape(): ControlPlaneErrorShape {
    return {
      code: this.code,
      ...(this.service ? { service: this.service } : {}),
      ...(this.environment ? { environment: this.environment } : {}),
      ...(this.operation ? { operation: this.operation } : {}),
      retryable: this.retryable,
      timestamp: new Date().toISOString(),
      ...(this.correlationId ? { correlationId: this.correlationId } : {}),
      message: this.message,
    };
  }
}

/** Map an upstream HTTP status to a canonical code (safe, generic messages). */
export function codeFromUpstreamStatus(status: number): ControlPlaneErrorCode {
  if (status === 401) return "UNAUTHORIZED";
  if (status === 403) return "FORBIDDEN";
  if (status === 404) return "NOT_FOUND";
  if (status === 501) return "CAPABILITY_UNSUPPORTED";
  if (status === 503) return "SERVICE_UNAVAILABLE";
  if (status >= 500) return "UPSTREAM_ERROR";
  if (status >= 400) return "BAD_REQUEST";
  return "UPSTREAM_ERROR";
}

/** Normalize any thrown value into a ControlPlaneError without leaking details. */
export function normalizeThrown(
  err: unknown,
  ctx: { service?: string; environment?: EnvironmentId; operation?: string; correlationId?: string },
): ControlPlaneError {
  if (err instanceof ControlPlaneError) return err;
  if (err instanceof DOMException && err.name === "AbortError") {
    return new ControlPlaneError("TIMEOUT", "upstream timed out", ctx);
  }
  // Fetch/connection errors — do not surface the raw message to the browser.
  return new ControlPlaneError("SERVICE_UNAVAILABLE", "upstream unreachable", ctx);
}

/** Map a canonical error code to the per-source state used in snapshots. */
export function sourceStateForCode(code: ControlPlaneErrorCode): SourceState {
  switch (code) {
    case "TIMEOUT":
      return "timeout";
    case "UNAUTHORIZED":
    case "FORBIDDEN":
      return "unauthorized";
    case "CAPABILITY_UNSUPPORTED":
      return "unsupported";
    case "CAPABILITY_UNAVAILABLE":
    case "SERVICE_UNAVAILABLE":
    case "CONFIGURATION_ERROR":
      return "unavailable";
    case "PARTIAL_DATA":
      return "degraded";
    default:
      return "error";
  }
}
