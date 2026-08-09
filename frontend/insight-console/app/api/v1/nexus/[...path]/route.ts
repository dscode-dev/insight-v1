// /api/v1/nexus/* — Insight Nexus, via the Control Plane.
//
// The console holds no Nexus credential and knows no Nexus address. This
// forwards to `insight-console-api`, which owns the service-to-service token
// and classifies every path against a closed allow-list before it goes
// anywhere (see `src/nexus/path-policy.ts` there).
//
// Nexus had no console surface at all until now: it authenticated operators
// against the public Gateway, which insight-context.md v2.0 excludes from
// operators, so its whole admin API answered 503.
//
// PERMISSIONS ARE CHECKED TWICE, on purpose and at different levels. Here it
// is coarse — can this operator write at all — so an unauthorized click fails
// fast with a clear message instead of costing a round trip. Nexus then
// checks what the specific route requires against what the Control Plane
// forwarded. Neither check makes the other redundant: this one does not know
// Nexus's routes, and that one does not run if the request never leaves.

import { ConsoleApiError } from "@/lib/admin-api";
import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { consoleApiCall } from "@/lib/control-plane/adapters/console-api";

async function proxy(req: Request): Promise<Response> {
  const operator = await requireOperator();
  const url = new URL(req.url);
  const marker = "/nexus/";
  const path = decodeURIComponent(url.pathname.split(marker)[1] ?? "");
  if (path === "") {
    throw new ConsoleApiError(400, "empty_nexus_path");
  }

  if (req.method !== "GET") {
    if (!operator.permissions.includes("config.write")) {
      throw new ConsoleApiError(403, "permission_denied");
    }
  }

  const hasBody = req.method !== "GET" && req.method !== "DELETE";
  const body = hasBody ? await req.json().catch(() => ({})) : undefined;
  return consoleApiCall(
    `/nexus/${path}${url.search || ""}`,
    req.method,
    body,
  );
}

export const GET = withApiHandler(proxy);
export const POST = withApiHandler(proxy);
export const PUT = withApiHandler(proxy);
export const PATCH = withApiHandler(proxy);
