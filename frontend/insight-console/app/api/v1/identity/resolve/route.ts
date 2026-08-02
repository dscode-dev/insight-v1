// GET /api/v1/identity/resolve — CONSOLE-IDENTITY-A.
// Server-side identity resolution via the Gateway authority. The browser cannot
// forge identity; it may pass an optional delegation_id REFERENCE only.
import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { readSessionCookie } from "@/lib/session";
import { resolveOperationalIdentity } from "@/lib/control-plane/adapters/identity";

export const dynamic = "force-dynamic";

export const GET = withApiHandler(async (req) => {
  await requireOperator();
  const url = new URL(req.url);
  const correlationId = req.headers.get("x-request-id");
  const delegationId = url.searchParams.get("delegation_id");
  const resolved = await resolveOperationalIdentity(readSessionCookie(), correlationId, delegationId);
  return Response.json(resolved, { headers: { "cache-control": "no-store" } });
});
