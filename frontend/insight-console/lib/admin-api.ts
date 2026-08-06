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

import { consoleApiCall } from "@/lib/control-plane/adapters/console-api";

// ADMIN_API_BASE_URL and ADMIN_API_INTERNAL_TOKEN are deliberately NOT
// read here any more. They moved to the Control Plane along with the
// calls that used them — a dead env read is how a "we no longer talk to
// that service" claim quietly stops being true.

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

/**
 * Every admin/social call now leaves through the Insight Control Plane.
 *
 * insight-context.md v2.0: the console "nunca acessa diretamente os
 * demais serviços". The cloud Gateway is a Product-plane service, so the
 * Control Plane is what talks to it on an operator's behalf — and
 * ADMIN_API_INTERNAL_TOKEN moved there with the calls. This process no
 * longer holds it, and no longer sends the operator token either: the
 * Control Plane already resolved the session and derives attribution
 * from it.
 *
 * The path is passed through unchanged; the Control Plane classifies it
 * against a closed allow-list (`gateway-path-policy.ts`) and refuses
 * anything it does not recognise.
 */
export async function adminFetch(
  path: string,
  options: AdminCallOptions = {},
): Promise<Response> {
  const { method = "GET", body } = options;
  const normalized = path.startsWith("/") ? path.slice(1) : path;
  return consoleApiCall(`product-plane/${normalized}`, method, body);
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
