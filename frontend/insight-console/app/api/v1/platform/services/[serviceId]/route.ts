// GET /api/v1/platform/services/:serviceId — one service (public read model).
// The id is validated against the registry — it never becomes a URL (no SSRF).

import { ConsoleApiError } from "@/lib/admin-api";
import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { ServiceRegistry } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

function idFromUrl(url: string): string {
  const parts = new URL(url).pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] ?? "");
}

export const GET = withApiHandler(async (req) => {
  await requirePermission("console.access");
  const id = idFromUrl(req.url);
  if (!ServiceRegistry.isValidId(id)) {
    throw new ConsoleApiError(404, "service_not_found", { upstreamCode: "invalid_service_id" });
  }
  const svc = ServiceRegistry.get(id);
  if (!svc) throw new ConsoleApiError(404, "service_not_found");
  return Response.json(svc, { headers: { "cache-control": "no-store" } });
});
