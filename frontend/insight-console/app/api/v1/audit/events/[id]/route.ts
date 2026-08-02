// GET /api/v1/audit/events/:id — one canonical audit event (CONSOLE-SECURITY-A0).
// Authenticated + authorized (audit.read). The id is validated as a lookup key —
// never used to build a query beyond a parameterized equality.

import { ConsoleApiError } from "@/lib/admin-api";
import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { getAuditRepository } from "@/lib/control-plane/security";

export const dynamic = "force-dynamic";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function idFromUrl(url: string): string {
  const parts = new URL(url).pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] ?? "");
}

export const GET = withApiHandler(async (req) => {
  await requirePermission("audit.read");
  const id = idFromUrl(req.url);
  if (!UUID_RE.test(id)) {
    throw new ConsoleApiError(400, "invalid_event_id");
  }
  const event = await getAuditRepository().getById(id);
  if (!event) throw new ConsoleApiError(404, "audit_event_not_found");
  return Response.json(event, { headers: { "cache-control": "no-store" } });
});
