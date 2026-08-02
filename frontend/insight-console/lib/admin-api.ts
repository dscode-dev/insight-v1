// Admin API client — the single integration seam between the Console
// BFF and the platform's admin surface (the Gateway in the target
// architecture; configured via ADMIN_API_BASE_URL). Browser code
// NEVER imports this file; only server-side route handlers
// (`app/api/**`) do. The browser talks exclusively to /api on the
// Console origin.
//
// Why a thin client (not OpenAPI codegen):
//   * The admin surface is small + stable; codegen would add a build
//     step for ~10 endpoints.
//   * Errors are hand-shaped into ConsoleApiError so the BFF can
//     translate them into structured 4xx/5xx for the browser.

import { z } from "zod";

const ADMIN_API_BASE_URL =
  process.env.ADMIN_API_BASE_URL ?? "https://insight-api.konohalabs.com.br/v1";
const ADMIN_API_INTERNAL_TOKEN = process.env.ADMIN_API_INTERNAL_TOKEN ?? "";

export class ConsoleApiError extends Error {
  readonly status: number;
  readonly upstreamCode?: string;
  readonly correlationId?: string;

  constructor(
    status: number,
    message: string,
    opts: { upstreamCode?: string; correlationId?: string } = {},
  ) {
    super(message);
    this.status = status;
    this.upstreamCode = opts.upstreamCode;
    this.correlationId = opts.correlationId;
  }
}

export interface AdminCallOptions {
  /** Opaque Gateway operator session token forwarded as Bearer auth. */
  operatorToken?: string;
  /** Per-request correlation id; propagated to logs end-to-end. */
  correlationId?: string;
  /** Method override. Defaults to GET. */
  method?: "GET" | "POST" | "PUT" | "DELETE";
  /** JSON body — only for non-GET. */
  body?: unknown;
  /** Hard timeout (ms). Default 5000. */
  timeoutMs?: number;
}

function adminURL(path: string): string {
  const base = ADMIN_API_BASE_URL.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (base.endsWith("/v1") && normalizedPath.startsWith("/v1/")) {
    return `${base}${normalizedPath.slice(3)}`;
  }
  return `${base}${normalizedPath}`;
}

/**
 * Low-level fetch wrapper. Returns the raw Response so individual
 * BFF routes can shape the response (some pass through, some
 * transform, some aggregate). Throws ConsoleApiError on transport
 * failures (timeout, connection reset). HTTP-level errors are NOT
 * thrown — the caller inspects status.
 */
export async function adminFetch(
  path: string,
  options: AdminCallOptions = {},
): Promise<Response> {
  if (!ADMIN_API_INTERNAL_TOKEN && process.env.NODE_ENV === "production") {
    throw new ConsoleApiError(503, "admin_api_token_missing");
  }
  const { operatorToken, correlationId, method = "GET", body, timeoutMs = 5000 } =
    options;
  const url = adminURL(path);
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Console-Service-Token": ADMIN_API_INTERNAL_TOKEN,
  };
  if (operatorToken) headers["Authorization"] = `Bearer ${operatorToken}`;
  if (correlationId) headers["X-Request-Id"] = correlationId;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      // Server-side; no need for credentials.
      cache: "no-store",
    });
    return res;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ConsoleApiError(504, "admin_api_timeout", { correlationId });
    }
    throw new ConsoleApiError(502, "admin_api_unreachable", {
      correlationId,
      upstreamCode: (err as Error).message,
    });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Typed fetch with Zod parsing. Throws ConsoleApiError on:
 *   - transport failure
 *   - upstream 4xx / 5xx
 *   - schema mismatch
 *
 * Returns the parsed body. Use this when the route does pure
 * pass-through with a known shape; for routes that aggregate
 * multiple upstreams, call adminFetch directly + parse per call.
 */
export async function adminJson<T>(
  path: string,
  schema: z.ZodSchema<T>,
  options: AdminCallOptions = {},
): Promise<T> {
  const res = await adminFetch(path, options);
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new ConsoleApiError(502, "admin_api_invalid_json", {
      correlationId: options.correlationId,
    });
  }
  if (!res.ok) {
    const detail =
      (typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : null) ?? `upstream_${res.status}`;
    throw new ConsoleApiError(res.status, detail, {
      correlationId: options.correlationId,
    });
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new ConsoleApiError(502, "admin_api_schema_mismatch", {
      correlationId: options.correlationId,
      upstreamCode: parsed.error.message.slice(0, 200),
    });
  }
  return parsed.data;
}
