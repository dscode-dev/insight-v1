// GET /api/v1/platform/capabilities — Capability Registry read model.
// Descriptive discovery only (NOT authorization). Filters: ?service= ?domain=
// ?actionType=read|mutation. Every capability carries real evidence.

import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { CapabilityRegistry } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

export const GET = withApiHandler(async (req) => {
  await requirePermission("console.access");
  const url = new URL(req.url);
  const service = url.searchParams.get("service") ?? undefined;
  const domain = url.searchParams.get("domain") ?? undefined;
  const actionTypeRaw = url.searchParams.get("actionType");
  const actionType =
    actionTypeRaw === "read" || actionTypeRaw === "mutation" ? actionTypeRaw : undefined;
  return Response.json(
    { capabilities: CapabilityRegistry.list({ service, domain, actionType }) },
    { headers: { "cache-control": "no-store" } },
  );
});
