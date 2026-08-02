// GET /api/v1/ops/{events|tickets|runs|datasets|training|history|incidents|actions}.
// Read-only proxy to the Robozão Gateway operations API (the Console consumes
// ONLY the gateway). Operator-gated; query params forwarded.

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { ConsoleApiError } from "@/lib/admin-api";
import { robozaoOps } from "@/lib/robozao";

const ALLOWED_QUERY = new Set([
  "service", "severity", "status", "kind", "run_id", "limit",
  "offset", "category", "from", "to",
  "correlation_id", "request_id", "trace_id",
]);

export const GET = withApiHandler(async (req: Request) => {
  await requirePermission("console.access");
  const url = new URL(req.url);
  // resource = last non-empty path segment (works under the /console basePath).
  const segments = url.pathname.split("/").filter(Boolean);
  const resource = segments[segments.length - 1] ?? "";
  const out = new URLSearchParams();
  for (const [k, v] of url.searchParams) {
    if (ALLOWED_QUERY.has(k) && v) out.set(k, v);
  }
  try {
    const data = await robozaoOps(resource, out.toString());
    return Response.json(data, { headers: { "cache-control": "no-store" } });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "ops_unreachable";
    if (msg === "unknown_ops_resource") throw new ConsoleApiError(404, msg);
    throw new ConsoleApiError(502, msg);
  }
});
