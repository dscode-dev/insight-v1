// Server-side route-handler guard — Sprint 8 Part 1 + Part 15.
//
// Every /api/v1/** route handler MUST start with `requireOperator()`
// or `requirePermission()`. These functions:
//   1. Read the opaque Gateway session cookie.
//   2. Resolve the operator from Gateway.
//   3. Consume Gateway-issued permissions for local request gating.
//   4. Optionally check a required permission slug.
//
// If any step fails the function THROWS a `ConsoleApiError`. The
// shared `handleApiError()` translates that into a structured 4xx/5xx
// JSON body.
//
// The frontend NEVER decides what an operator can do — every mutation
// is re-validated here. This is the defence against IDOR + privilege
// escalation (Sprint 8 Part 15).

import { ConsoleApiError } from "@/lib/admin-api";
import { currentOperator } from "@/lib/session";
import type { ConsoleOperator, Permission } from "@/types/auth";

export async function requireOperator(): Promise<ConsoleOperator> {
  const op = await currentOperator();
  if (!op) {
    throw new ConsoleApiError(401, "unauthenticated");
  }
  return op;
}

export async function requirePermission(
  perm: Permission,
): Promise<ConsoleOperator> {
  const op = await requireOperator();
  if (!op.permissions.includes(perm)) {
    throw new ConsoleApiError(403, "permission_denied", {
      upstreamCode: perm,
    });
  }
  return op;
}

/**
 * Wraps a route handler with shared error handling. Use:
 *
 *   export const GET = withApiHandler(async (req) => {
 *     const op = await requirePermission("dlq.read");
 *     ...
 *     return Response.json({ ... });
 *   });
 */
export function withApiHandler(
  handler: (req: Request) => Promise<Response>,
): (req: Request) => Promise<Response> {
  return async (req: Request) => {
    const requestId = req.headers.get("x-request-id") ?? "";
    try {
      const res = await handler(req);
      // Stamp the correlation id on every response so the browser
      // can echo it back in a bug report.
      if (!res.headers.has("x-request-id") && requestId) {
        res.headers.set("x-request-id", requestId);
      }
      return res;
    } catch (err) {
      if (err instanceof ConsoleApiError) {
        return Response.json(
          {
            error: err.message,
            code: err.upstreamCode,
            request_id: requestId,
          },
          {
            status: err.status,
            headers: { "x-request-id": requestId },
          },
        );
      }
      // Unknown error — never leak the message; log + return 500.
      console.error("[console:api]", {
        path: new URL(req.url).pathname,
        request_id: requestId,
        err: err instanceof Error ? err.message : String(err),
      });
      return Response.json(
        { error: "internal_error", request_id: requestId },
        { status: 500, headers: { "x-request-id": requestId } },
      );
    }
  };
}
