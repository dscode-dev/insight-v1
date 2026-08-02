// GET /api/v1/platform/environments — Environment Registry read model.
// Server-owned topology; no URLs/secrets in the payload (CONSOLE-FOUNDATION-A).

import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { EnvironmentRegistry } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

export const GET = withApiHandler(async () => {
  await requirePermission("console.access");
  return Response.json(
    { environments: EnvironmentRegistry.list() },
    { headers: { "cache-control": "no-store" } },
  );
});
