// GET /api/v1/platform/services — Service Registry public read model.
// Filters: ?environment= ?domain=. No endpoints or tokens in the payload.

import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { ServiceRegistry } from "@/lib/control-plane";
import { EnvironmentRegistry } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

export const GET = withApiHandler(async (req) => {
  await requirePermission("console.access");
  const url = new URL(req.url);
  const environment = url.searchParams.get("environment") ?? undefined;
  const domain = url.searchParams.get("domain") ?? undefined;
  // Validate the filter so it can never be a probe for arbitrary values.
  if (environment && !EnvironmentRegistry.isValidId(environment)) {
    return Response.json({ services: [] }, { headers: { "cache-control": "no-store" } });
  }
  return Response.json(
    { services: ServiceRegistry.list({ environment, domain }) },
    { headers: { "cache-control": "no-store" } },
  );
});
