// GET /api/v1/platform/environments/:environmentId — one environment.
// The id is validated against the registry — it is never used to build a URL.

import { ConsoleApiError } from "@/lib/admin-api";
import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { EnvironmentRegistry } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

function idFromUrl(url: string): string {
  const parts = new URL(url).pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] ?? "");
}

export const GET = withApiHandler(async (req) => {
  await requirePermission("console.access");
  const id = idFromUrl(req.url);
  if (!EnvironmentRegistry.isValidId(id)) {
    throw new ConsoleApiError(404, "environment_not_found", { upstreamCode: "invalid_environment_id" });
  }
  const env = EnvironmentRegistry.get(id);
  if (!env) throw new ConsoleApiError(404, "environment_not_found");
  return Response.json(env, { headers: { "cache-control": "no-store" } });
});
